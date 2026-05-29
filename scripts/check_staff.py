import sys
import os

sys.path.insert(0, os.getcwd())
from uraas.config.institutions import get_registry

registry = get_registry()
for inst in registry.list_all():
    print(f"{inst.short_name}: {len(inst.staff_names)} staff (File: {inst.staff_file})")
