from troposphere import Ref, ec2

from .instances import created_instances
from .template import template
from .vpc import nat_gateway, private_route_table

if nat_gateway:
    private_nat_route = ec2.Route(
        "PrivateNatRoute",
        template=template,
        RouteTableId=Ref(private_route_table),
        DestinationCidrBlock="0.0.0.0/0",
        NatGatewayId=Ref(nat_gateway),
    )
else:
    private_nat_route = ec2.Route(
        "PrivateNatRoute",
        template=template,
        RouteTableId=Ref(private_route_table),
        DestinationCidrBlock="0.0.0.0/0",
        InstanceId=Ref(created_instances[("router", "")]),
    )
