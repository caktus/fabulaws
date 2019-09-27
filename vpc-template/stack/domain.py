from troposphere import Ref

from .common import environments
from .template import template
from .utils import ParameterWithDefaults as Parameter


domains = {}
for environment in environments:
    domains[environment] = Ref(
        template.add_parameter(
            Parameter(
                "DomainNames%s" % environment.title(),
                Description="A comma-separated list of FQDNs for %s." % environment,
                Type="CommaDelimitedList",
            ),
            group="Global",
            label="Domain Names (%s)" % environment,
        )
    )
