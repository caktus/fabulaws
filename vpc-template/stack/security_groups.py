from troposphere import Parameter, Ref
from troposphere.ec2 import SecurityGroup, SecurityGroupIngress, SecurityGroupRule

from .template import template
from .vpc import vpc, vpc_cidr

# CloudFormation uses -1 as a special value to signify 'ALL' in various parameters
ALL = "-1"

local_cidr = template.add_parameter(
    Parameter(
        "LocalCidr",
        Description='CIDR block from which to allow restricted access. Set this to "<your IP>/32".',
        Type="String",
        Default="0.0.0.0/0",
    ),
    group="Networking",
    label="Local CIDR",
)

# Only allow outside VPN access to the router
router_security_group = template.add_resource(
    SecurityGroup(
        "RouterSecurityGroup",
        GroupDescription="Allows SSH and HTTPS access from LocalCidr, and OpenVPN from anywhere.",
        VpcId=Ref(vpc),
        SecurityGroupIngress=[
            SecurityGroupRule(
                IpProtocol="tcp", FromPort=22, ToPort=22, CidrIp=Ref(local_cidr)
            ),
            SecurityGroupRule(
                IpProtocol="tcp", FromPort=443, ToPort=443, CidrIp=Ref(local_cidr)
            ),
            SecurityGroupRule(
                IpProtocol="udp", FromPort=1194, ToPort=1194, CidrIp="0.0.0.0/0"
            ),
            # Allow all traffic from our VPC, for NAT purposes
            SecurityGroupRule(
                IpProtocol=ALL, FromPort=ALL, ToPort=ALL, CidrIp=Ref(vpc_cidr)
            ),
        ],
    )
)

backend_security_group = template.add_resource(
    SecurityGroup(
        "BackendSecurityGroup",
        GroupDescription="Allow full access between the Backend Instances",
        VpcId=Ref(vpc),
    )
)
# Allow unlimited traffic between all backend servers
template.add_resource(
    SecurityGroupIngress(
        "BackendSecurityGroupIngressRule",
        GroupId=Ref(backend_security_group),
        IpProtocol=ALL,
        SourceSecurityGroupId=Ref(backend_security_group),
        FromPort=ALL,
        ToPort=ALL,
    )
)
# Allow unlimited traffic from router to backend servers
template.add_resource(
    SecurityGroupIngress(
        "RouterToBackendSecurityGroupIngressRule",
        GroupId=Ref(backend_security_group),
        IpProtocol=ALL,
        SourceSecurityGroupId=Ref(router_security_group),
        FromPort=ALL,
        ToPort=ALL,
    )
)

aws_elb_security_group = SecurityGroup(
    "AwsElbSecurityGroup",
    template=template,
    GroupDescription="AWS elastic load balancer security group.",
    VpcId=Ref(vpc),
    SecurityGroupIngress=[
        # allow incoming traffic from the public internet to the AWS ELB on ports 80 and 443
        SecurityGroupRule(
            IpProtocol="tcp", FromPort=port, ToPort=port, CidrIp="0.0.0.0/0"
        )
        for port in ["80", "443"]
    ],
)

web_security_group = SecurityGroup(
    "WebServerSecurityGroup",
    template=template,
    GroupDescription="Backend web server security group.",
    VpcId=Ref(vpc),
    SecurityGroupIngress=[
        # allow incoming traffic from the AWS ELB on ports 80 and 443 only
        SecurityGroupRule(
            IpProtocol="tcp",
            FromPort="80",
            ToPort="80",
            SourceSecurityGroupId=Ref(aws_elb_security_group),
        ),
        SecurityGroupRule(
            IpProtocol="tcp",
            FromPort="443",
            ToPort="443",
            SourceSecurityGroupId=Ref(aws_elb_security_group),
        ),
    ],
)
