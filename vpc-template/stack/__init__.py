from . import assets  # noqa: F401
from . import vpc  # noqa: F401
from . import template
from . import instances  # noqa: F401
from . import networking  # noqa: F401
from . import load_balancer  # noqa: F401

print(template.template.to_json())
