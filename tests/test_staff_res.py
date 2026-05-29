import os

from uraas.config.institutions import get_registry

if __name__ == "__main__":
    registry = get_registry()
    for inst in registry.list_all():
        print(
            f"{inst.short_name}: {len(inst.staff_names)} names, resolved path: {inst._resolve_staff_file()}"
        )
        if not os.path.exists(inst._resolve_staff_file()):
            print(f"  ERROR: Path does not exist!")
