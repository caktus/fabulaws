from troposphere import (
    AWS_STACK_NAME,
    GetAtt,
    Join,
    Output,
    Parameter,
    Ref,
    Tags,
    autoscaling,
    ec2,
    iam,
)

from .assets import assets_management_policy
from .common import environments
from .load_balancer import load_balancers
from .logs import logging_policy
from .security_groups import router_security_group, web_security_group
from .template import template
from .vpc import private_a_subnet, private_b_subnet, public_a_subnet

router_ami = template.add_parameter(
    Parameter(
        "RouterAMI",
        Description="pfSense AMI from the AWS marketplace in the same region as this stack",
        Type="String",
        Default="ami-089c333c4d9b09ffc",  # us-east-1
    ),
    group="EC2",
    label="Router AMI",
)

key_name = template.add_parameter(
    Parameter(
        "KeyName",
        Description="Name of an existing EC2 KeyPair to enable SSH access to "
        "the AWS EC2 instances",
        Type="AWS::EC2::KeyPair::KeyName",
        ConstraintDescription="must be the name of an existing EC2 KeyPair.",
    ),
    group="EC2",
    label="SSH Key Name",
)

# # EC2 instance role
# instance_role = iam.Role(
#     "InstanceRole",
#     template=template,
#     AssumeRolePolicyDocument=dict(
#         Statement=[
#             dict(
#                 Effect="Allow",
#                 Principal=dict(Service=["ec2.amazonaws.com"]),
#                 Action=["sts:AssumeRole"],
#             )
#         ]
#     ),
#     Path="/",
#     Policies=[assets_management_policy, logging_policy],
# )

# # EC2 instance profile
# instance_profile = iam.InstanceProfile(
#     "InstanceProfile", template=template, Path="/", Roles=[Ref(instance_role)]
# )

# Root Volume Sizes
# These are just the defaults. Typically these values should not be changed, as
# doing so will result in instance recreation. Instead you can increase the size
# of the EBS volume via the AWS console (followed by resize2fs on the instance):
# https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/requesting-ebs-volume-modifications.html#modify-ebs-volume
ROOT_VOLUME_SIZES = {"router": 8}

# Instance Types
# See: https://aws.amazon.com/blogs/aws/new-t2-xlarge-and-t2-2xlarge-instances/
INSTANCE_TYPES = {("router", ""): "t2.nano"}


def ebs_block_device(volume_size):
    return [
        ec2.BlockDeviceMapping(
            DeviceName="/dev/sda1", Ebs=ec2.EBSBlockDevice(VolumeSize=volume_size)
        )
    ]


common_ec2_properties = dict(KeyName=Ref(key_name))

ec2_instance_definitions = {
    ("router", ""): dict(
        ImageId=Ref(router_ami),
        SecurityGroupIds=[Ref(router_security_group)],
        SubnetId=Ref(public_a_subnet),
        # https://docs.aws.amazon.com/AmazonVPC/latest/UserGuide/VPC_NAT_Instance.html#EIP_Disable_SrcDestCheck
        SourceDestCheck=False,
        # Prevent accidental deletion of the router (in case this stack ever needs to be deleted,
        # one may need to set this to False first).
        DisableApiTermination=True,
    )
}

created_instances = {}

for (name, environment), properties in ec2_instance_definitions.items():
    default_properties = dict(common_ec2_properties)
    # remove all digits from the instance name (to simplify volume size / instance type lookups)
    name_no_digits = name.translate(str.maketrans("", "", "1234567890"))
    default_properties.update(
        dict(
            BlockDeviceMappings=ebs_block_device(ROOT_VOLUME_SIZES[name_no_digits]),
            InstanceType=INSTANCE_TYPES[(name_no_digits, environment)],
        )
    )
    # make sure any instance-specific properties override the common/defaults
    default_properties.update(properties)
    instance_name = "{}{}".format(environment, name)
    created_instances[(name, environment)] = template.add_resource(
        ec2.Instance(
            title=instance_name,
            Tags=Tags(
                Name=Join("-", [Ref("AWS::StackName"), instance_name]),
                Environment=environment,
            ),
            **default_properties
        )
    )

# Associate the Elastic IP separately, so it doesn't change when the instance changes.
router_eip = template.add_resource(ec2.EIP("RouterEIP", Domain="vpc"))
template.add_resource(
    ec2.EIPAssociation(
        "RouterEipAssociation",
        InstanceId=Ref(created_instances[("router", "")]),
        # Might need to switch the following line to EIP=Ref(router_eip) if
        # we ever create this stack in a VPC-only account.
        AllocationId=GetAtt(router_eip, "AllocationId"),
    )
)

template.add_output(
    [
        Output(
            "RouterPublicIP",
            Description="Public IP address of router",
            Value=Ref(router_eip),
        )
    ]
)

for environment in environments:
    instance_configuration_name = "LaunchConfiguration%s" % environment.title()
    autoscaling_group_name = "AutoScalingGroup%s" % environment.title()

    container_instance_configuration = autoscaling.LaunchConfiguration(
        instance_configuration_name,
        template=template,
        SecurityGroups=[Ref(web_security_group)],
        # We need a launch config to create an autoscaling group, so just use the router AMI/instance type.
        # We set the DesiredCapacity to 0 below, so none of these will actually get created.
        InstanceType=INSTANCE_TYPES[("router", "")],
        ImageId=Ref(router_ami),
        KeyName=Ref(key_name),
    )

    autoscaling_group = autoscaling.AutoScalingGroup(
        autoscaling_group_name,
        template=template,
        VPCZoneIdentifier=[Ref(private_a_subnet), Ref(private_b_subnet)],
        # Start with no instances (will be added by fabulaws)
        MinSize="0",
        MaxSize="32",
        # Don't specify DesiredCapacity to avoid updating that attribute
        LaunchConfigurationName=Ref(container_instance_configuration),
        LoadBalancerNames=[Ref(load_balancers[environment])],
        HealthCheckType="ELB",
        HealthCheckGracePeriod=300,
        Tags=[
            {
                "Key": "Name",
                "Value": Join("-", [Ref(AWS_STACK_NAME), "web_worker"]),
                "PropagateAtLaunch": True,
            }
        ],
    )
