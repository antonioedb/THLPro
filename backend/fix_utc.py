import os
import re

ROOT = "."

pattern_import = re.compile(r"^from datetime import (.+)$", re.M)

for folder, _, files in os.walk(ROOT):
    if ".venv" in folder:
        continue
    for name in files:
        if not name.endswith(".py"):
            continue
        path = os.path.join(folder, name)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        if "UTC" not in content:
            continue

        def fix_import(m):
            imports = m.group(1)
            # remove UTC da lista
            parts = [p.strip() for p in imports.split(",")]
            parts = [p for p in parts if p and p != "UTC"]
            if "timezone" not in parts:
                parts.append("timezone")
            return "from datetime import " + ", ".join(parts)

        new_content = pattern_import.sub(fix_import, content)

        # adiciona UTC = timezone.utc após o import, se ainda não existir
        if "UTC = timezone.utc" not in new_content:
            new_content = re.sub(
                r"(^from datetime import .+$)",
                r"\1\nUTC = timezone.utc",
                new_content,
                count=1,
                flags=re.M,
            )

        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)

        print("Corrigido:", path)