from fabulaws.ubuntu.instances.base import UbuntuInstance

__all__ = ['MicroLucidInstance', 'SmallLucidInstance']


class MicroLucidInstance(UbuntuInstance):
    """
    Sample Micro instance running Ubuntu Lucid on an EBS root filesystem.
    """
    ami = 'ami-3e02f257' # Lucid EBS
    instance_type = 't1.micro'
    key_prefix = 'micro-ubuntu-'


class SmallLucidInstance(UbuntuInstance):
    """
    Sample Small instance running Ubuntu Lucid on on an instance-store root
    filesystem.
    """
    ami = 'ami-7000f019' # Lucid instance store
    instance_type = 'm1.small'
    key_prefix = 'small-ubuntu-'
