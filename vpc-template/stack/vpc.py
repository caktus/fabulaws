import os

from troposphere import GetAtt, Parameter, Ref
from troposphere.ec2 import (
    EIP,
    VPC,
    InternetGateway,
    NatGateway,
    Route,
    RouteTable,
    Subnet,
    SubnetRouteTableAssociation,
    VPCGatewayAttachment,
)

from .template import template

USE_NAT_GATEWAY = os.environ.get("USE_NAT_GATEWAY") == "on"

primary_az = template.add_parameter(
    Parameter(
        "PrimaryAZ",
        Description="The primary availability zone for creating resources.",
        Type="AWS::EC2::AvailabilityZone::Name",
    ),
    group="Global",
    label="Primary Availability Zone",
)


secondary_az = template.add_parameter(
    Parameter(
        "SecondaryAZ",
        Description="The secondary availability zone for creating resources. Must differ from primary zone.",
        Type="AWS::EC2::AvailabilityZone::Name",
    ),
    group="Global",
    label="Secondary Availability Zone",
)


vpc_cidr = "10.1.0.0/22"
vpc = VPC(
    "Vpc",
    template=template,
    CidrBlock=vpc_cidr,
    EnableDnsSupport=True,
    EnableDnsHostnames=True,
)


# Allow outgoing to outside VPC
internet_gateway = InternetGateway("InternetGateway", template=template)


# Attach Gateway to VPC
VPCGatewayAttachment(
    "GatewayAttachement",
    template=template,
    VpcId=Ref(vpc),
    InternetGatewayId=Ref(internet_gateway),
)


# Public route table
public_route_table = RouteTable("PublicRouteTable", template=template, VpcId=Ref(vpc))

public_route = Route(
    "PublicRoute",
    template=template,
    GatewayId=Ref(internet_gateway),
    DestinationCidrBlock="0.0.0.0/0",
    RouteTableId=Ref(public_route_table),
)


# Holds public instances & elastic load balancers
public_a_subnet_cidr = "10.1.0.0/24"
public_a_subnet = Subnet(
    "PublicASubnet",
    template=template,
    VpcId=Ref(vpc),
    CidrBlock=public_a_subnet_cidr,
    MapPublicIpOnLaunch=True,  # required when routing through an InternetGateway
    AvailabilityZone=Ref(primary_az),
)

SubnetRouteTableAssociation(
    "PublicASubnetRouteTableAssociation",
    template=template,
    RouteTableId=Ref(public_route_table),
    SubnetId=Ref(public_a_subnet),
)

public_b_subnet_cidr = "10.1.1.0/24"
public_b_subnet = Subnet(
    "PublicBSubnet",
    template=template,
    VpcId=Ref(vpc),
    CidrBlock=public_b_subnet_cidr,
    MapPublicIpOnLaunch=True,  # required when routing through an InternetGateway
    AvailabilityZone=Ref(secondary_az),
)

SubnetRouteTableAssociation(
    "PublicBSubnetRouteTableAssociation",
    template=template,
    RouteTableId=Ref(public_route_table),
    SubnetId=Ref(public_b_subnet),
)


# Private route table
if USE_NAT_GATEWAY:
    # NAT
    nat_ip = EIP("NatIp", template=template, Domain="vpc")
    nat_gateway = NatGateway(
        "NatGateway",
        template=template,
        AllocationId=GetAtt(nat_ip, "AllocationId"),
        SubnetId=Ref(public_a_subnet),
    )
else:
    nat_gateway = None

# Note: private route is added to this table in networking.py (after we know the NAT instance ID)
private_route_table = RouteTable("PrivateRouteTable", template=template, VpcId=Ref(vpc))


# Holds backends instances
private_a_subnet_cidr = "10.1.2.0/24"
private_a_subnet = Subnet(
    "PrivateASubnet",
    template=template,
    VpcId=Ref(vpc),
    CidrBlock=private_a_subnet_cidr,
    MapPublicIpOnLaunch=False,
    AvailabilityZone=Ref(primary_az),
)

SubnetRouteTableAssociation(
    "PrivateARouteTableAssociation",
    template=template,
    SubnetId=Ref(private_a_subnet),
    RouteTableId=Ref(private_route_table),
)


private_b_subnet_cidr = "10.1.3.0/24"
private_b_subnet = Subnet(
    "PrivateBSubnet",
    template=template,
    VpcId=Ref(vpc),
    CidrBlock=private_b_subnet_cidr,
    MapPublicIpOnLaunch=False,
    AvailabilityZone=Ref(secondary_az),
)

SubnetRouteTableAssociation(
    "PrivateBRouteTableAssociation",
    template=template,
    SubnetId=Ref(private_b_subnet),
    RouteTableId=Ref(private_route_table),
)
