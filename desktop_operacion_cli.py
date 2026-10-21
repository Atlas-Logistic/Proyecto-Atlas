"""Canal manual de Desktop. No inicia ni consume PULL."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from atlas_core.desktop_operacion import ejecutar

if __name__ == '__main__':
    try:
        print(json.dumps(ejecutar(json.load(sys.stdin)),ensure_ascii=True))
    except Exception as e:
        print(str(e),file=sys.stderr)
        sys.exit(1)
