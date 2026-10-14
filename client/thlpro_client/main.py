from __future__ import annotations

import argparse
import os
import platform
import threading
import time

from thlpro_client.api_client import APIError, THLProAPIClient
from thlpro_client.app_paths import CLIENT_MUTEX_NAME, ensure_app_dirs
from thlpro_client.capture_service import CaptureService
from thlpro_client.compat_windows import (
    create_single_instance_lock,
    release_single_instance_lock,
)
from thlpro_client.config import ConfigStore
from thlpro_client.config_poller import ConfigPollerService
from thlpro_client.dedup_cache import QuoteDeduplicator
from thlpro_client.logger import configure_logging
from thlpro_client.queue_store import OfflineQueue
from thlpro_client.rtd_client import create_rtd_client
from thlpro_client.sender_service import SenderService
from thlpro_client.supervisor import WatchdogSupervisor, WorkerSpec
from thlpro_client.tk_config_window import ConfigWindow
from thlpro_client.tray_ui import TrayApp


VERSION = "0.4.0"

# Limite total de espera pelos serviços durante o encerramento.
SHUTDOWN_TIMEOUT_SECONDS = 45.0

VALID_RTD_MODES = {
    "excel_bridge",
    "excel",
    "com",
    "com_probe",
    "probe",
    "profit_api",
    "simulate",
}


def resolve_rtd_mode(
    config_simulate: bool,
    simulate_override: bool | None,
    cli_rtd_mode: str | None,
) -> str:
    """
    Mantém a regra de seleção existente:

    1. Simulação solicitada por CLI, configuração ou variável SIMULATE.
    2. --rtd-mode.
    3. Variável RTD_MODE.
    4. excel_bridge.
    """
    if simulate_override is True:
        return "simulate"

    if config_simulate or os.getenv("SIMULATE", "0") == "1":
        return "simulate"

    selected = (
        cli_rtd_mode
        or os.getenv("RTD_MODE", "")
        or "excel_bridge"
    ).lower().strip()

    if selected not in VALID_RTD_MODES:
        valid = ", ".join(sorted(VALID_RTD_MODES))
        raise RuntimeError(
            f"RTD_MODE inválido: {selected!r}. Modos aceitos: {valid}."
        )

    return selected


def log_rtd_mode_warning(logger, rtd_mode: str) -> None:
    if rtd_mode in {"excel_bridge", "excel", "com"}:
        logger.warning(
            "Modo RTD=%s: usa Excel oculto para ler o RTD do Profit. "
            "Durante o teste do cliente, mantenha fechadas as planilhas "
            "manuais que também usam RTD.",
            rtd_mode,
        )
        return

    if rtd_mode in {"com_probe", "probe"}:
        logger.warning(
            "Modo RTD=%s: diagnóstico COM sem Excel. "
            "Este modo não captura nem envia cotações.",
            rtd_mode,
        )
        return

    if rtd_mode == "profit_api":
        logger.info(
            "Modo RTD=profit_api: integração ainda depende "
            "da implementação da API/plugin."
        )
        return

    if rtd_mode == "simulate":
        logger.info(
            "Modo RTD=simulate: serão geradas cotações de teste."
        )


def run_client(
    simulate_override: bool | None = None,
    no_gui: bool = False,
    rtd_mode_override: str | None = None,
) -> int:
    paths = ensure_app_dirs()
    log_path = paths["logs"] / "thlpro_client.log"
    logger = configure_logging(str(log_path))

    lock_obj, already_running = create_single_instance_lock(
        CLIENT_MUTEX_NAME
    )

    if already_running:
        logger.error(
            "Já existe uma instância do THLPro Client em execução."
        )
        return 2

    shutdown_requested = threading.Event()
    shutdown_lock = threading.Lock()
    shutdown_signalled = False

    capture = None
    sender = None
    poller = None
    supervisor = None
    watchdog_thread = None

    worker_done: dict[str, threading.Event] = {}
    worker_started: dict[str, threading.Event] = {}

    runtime_password = ""

    # Estado do botão da bandeja, não da conexão RTD.
    capture_paused_by_tray = False

    def request_shutdown() -> None:
        """
        Apenas sinaliza os serviços.

        Não acessa o Excel e não aguarda workers no callback da bandeja.
        """
        nonlocal shutdown_signalled

        shutdown_requested.set()

        with shutdown_lock:
            if shutdown_signalled:
                return

            shutdown_signalled = True
            logger.info("Encerramento solicitado; sinalizando serviços.")

            # Primeiro impede novas reinicializações pelo watchdog.
            if supervisor is not None:
                try:
                    supervisor.stop()
                except Exception:
                    logger.exception("Falha ao sinalizar supervisor.")

            for name, service in (
                ("config_poller", poller),
                ("capture", capture),
                ("sender", sender),
            ):
                if service is None:
                    continue

                try:
                    service.stop()
                except Exception:
                    logger.exception(
                        "Falha ao sinalizar serviço %s.",
                        name,
                    )

    def make_worker_target(name: str, target):
        """
        Envolve o worker para registrar sua conclusão.

        Evita depender dos atributos internos do WatchdogSupervisor.
        """
        done = threading.Event()
        started = threading.Event()

        worker_done[name] = done
        worker_started[name] = started

        def wrapped() -> None:
            done.clear()
            started.set()

            try:
                if shutdown_requested.is_set():
                    return

                target()
            finally:
                done.set()
                logger.info("Worker finalizado: %s", name)

        return wrapped

    def wait_for_shutdown() -> None:
        deadline = (
            time.monotonic() + SHUTDOWN_TIMEOUT_SECONDS
        )

        for name, done in worker_done.items():
            if not worker_started[name].is_set():
                continue

            remaining = max(0.0, deadline - time.monotonic())

            if not done.wait(remaining):
                logger.warning(
                    "Tempo de espera esgotado para %s. "
                    "Não será feito fechamento RTD por outra thread.",
                    name,
                )

        if watchdog_thread is not None:
            remaining = max(0.0, deadline - time.monotonic())
            watchdog_thread.join(timeout=remaining)

            if watchdog_thread.is_alive():
                logger.warning(
                    "Watchdog ainda ativo após o limite de espera."
                )

    try:
        store = ConfigStore(paths["config"])
        config = store.load()

        def on_save(updated, password):
            nonlocal config, runtime_password

            config = updated
            runtime_password = password
            store.save(config)

        if (not config.email or not config.server_url) and not no_gui:
            config_window = ConfigWindow(config, on_save=on_save)
            config_window.run()

        if simulate_override is not None:
            config.simulate = simulate_override

        if not config.computer_name:
            config.computer_name = platform.node() or "COMPUTADOR"
            store.save(config)

        api = THLProAPIClient(config.server_url)

        if runtime_password:
            api.login(config.email, runtime_password)

            registration = api.register_client(
                config.client_name,
                config.computer_name,
                VERSION,
            )

            store.set_api_key(config, registration["api_key"])

            logger.info(
                "Cliente registrado com id=%s",
                registration["client_id"],
            )

        api_key = store.read_api_key(config)

        if not api_key:
            raise RuntimeError(
                "API key não encontrada. "
                "Abra o app com interface e faça login."
            )

        api.api_key = api_key

        # Apenas consulta os ativos disponíveis.
        # Não aplica essa configuração à captura.
        initial_config = api.get_config(include_series=False)

        logger.info(
            "Cliente iniciado em modo sob demanda. "
            "Ativos-base disponíveis: %s.",
            len(initial_config.get("assets", [])),
        )
        logger.info("Arquivo de log: %s", log_path)
        logger.info("Banco da fila offline: %s", paths["queue"])

        rtd_mode = resolve_rtd_mode(
            config_simulate=config.simulate,
            simulate_override=simulate_override,
            cli_rtd_mode=rtd_mode_override,
        )

        log_rtd_mode_warning(logger, rtd_mode)

        # Cria o objeto, mas não chama connect() na thread principal.
        rtd = create_rtd_client(
            rtd_mode,
            logger,
            server_url=config.server_url,
            api_key=api_key,
        )

        queue = OfflineQueue(paths["queue"])

        dedup = QuoteDeduplicator(
            min_interval_ms=config.min_send_interval_ms
        )

        capture = CaptureService(
            logger=logger,
            rtd_client=rtd,
            deduplicator=dedup,
            queue_enqueue=queue.enqueue_many,
            queue_enqueue_asset=queue.enqueue_asset_quotes,
            simulation_mode=(rtd_mode == "simulate"),
        )

        sender = SenderService(
            logger=logger,
            api_client=api,
            queue=queue,
            heartbeat_seconds=config.heartbeat_seconds,
        )

        poller = ConfigPollerService(
            logger=logger,
            api_client=api,
            capture_service=capture,
            on_config=capture.set_pending_config,
            interval_seconds=config.poll_config_seconds,
        )

        workers = [
            WorkerSpec(
                name="capture_worker",
                target=make_worker_target(
                    "capture_worker",
                    capture.run_forever,
                ),
            ),
            WorkerSpec(
                name="sender_worker",
                target=make_worker_target(
                    "sender_worker",
                    sender.run_forever,
                ),
            ),
            WorkerSpec(
                name="config_poller_worker",
                target=make_worker_target(
                    "config_poller_worker",
                    poller.run_forever,
                ),
            ),
        ]

        supervisor = WatchdogSupervisor(logger, workers)
        supervisor.start_all()

        watchdog_thread = threading.Thread(
            target=supervisor.run_watchdog,
            name="watchdog",
            daemon=True,
        )
        watchdog_thread.start()

        # Não chama set_pending_config(initial_config).
        # Não chama start_capture() na inicialização.
        # O poller enfileira a demanda e libera a captura.

        def open_config_window():
            if shutdown_requested.is_set():
                return

            if no_gui:
                logger.info("UI desabilitada (modo no-gui).")
                return

            config_window = ConfigWindow(config, on_save=on_save)
            config_window.run()

        def toggle_capture():
            nonlocal capture_paused_by_tray

            if shutdown_requested.is_set():
                return

            capture_paused_by_tray = not capture_paused_by_tray

            if capture_paused_by_tray:
                capture.stop_capture()
                logger.info("Pausa solicitada pela bandeja.")
            else:
                capture.start_capture()
                logger.info(
                    "Retomada solicitada pela bandeja. "
                    "Sem configuração, a captura permanece aguardando."
                )

        if not no_gui:
            tray = TrayApp(
                logger=logger,
                on_open=open_config_window,
                on_toggle_capture=toggle_capture,
                on_exit=request_shutdown,
            )

            tray_thread = threading.Thread(
                target=tray.run,
                name="tray",
                daemon=True,
            )
            tray_thread.start()

        logger.info(
            "Cliente THLPro iniciado. rtd_mode=%s; simulação=%s; "
            "captura=somente sob demanda; consulta_demanda=%ss.",
            rtd_mode,
            rtd_mode == "simulate",
            config.poll_config_seconds,
        )

        oneshot_raw = os.getenv("THLPRO_ONESHOT_SECONDS", "")
        oneshot_seconds = (
            int(oneshot_raw)
            if oneshot_raw.isdigit()
            else 0
        )

        started_at = time.monotonic()

        while not shutdown_requested.wait(0.5):
            if (
                oneshot_seconds
                and time.monotonic() - started_at >= oneshot_seconds
            ):
                logger.info(
                    "Modo oneshot atingido (%ss). Encerrando.",
                    oneshot_seconds,
                )
                request_shutdown()

        return 0

    except (APIError, RuntimeError) as exc:
        logger.error("Falha de inicialização/execução: %s", exc)
        return 1

    except KeyboardInterrupt:
        logger.info("Encerrando cliente por teclado.")
        return 0

    except Exception:
        logger.exception("Falha inesperada no cliente.")
        return 1

    finally:
        try:
            request_shutdown()
            wait_for_shutdown()
            logger.info("Rotina de encerramento concluída.")
        finally:
            release_single_instance_lock(lock_obj)


def parse_args():
    parser = argparse.ArgumentParser(description="THLPro Client")

    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Força modo simulação",
    )

    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Executa sem abrir janela",
    )

    parser.add_argument(
        "--rtd-mode",
        choices=sorted(VALID_RTD_MODES),
        default=None,
        help=(
            "Modo de captura RTD. "
            "excel_bridge usa Excel oculto; "
            "com_probe apenas diagnostica; "
            "profit_api depende de implementação; "
            "simulate gera testes."
        ),
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    return run_client(
        simulate_override=True if args.simulate else None,
        no_gui=args.no_gui,
        rtd_mode_override=args.rtd_mode,
    )


if __name__ == "__main__":
    raise SystemExit(main())