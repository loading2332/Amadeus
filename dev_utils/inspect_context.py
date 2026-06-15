import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from amadeus.context import ContextBuilder, RuntimeContext
from amadeus.workspace import initialize_workspace

root = Path("/tmp/amadeus-demo")
initialize_workspace(root)

result = ContextBuilder().render(
    RuntimeContext(
        workspace_root=root,
        history=[],
        current_user_message="hello",
    )
)

print(result.messages)
print(result.system_prompt.breakdown)
