from fabulaws.ubuntu.packages.base import AptMixin


class Fail2banMixin(AptMixin):
    """
    FabulAWS Ubuntu mixin that installs the fail2ban server for rejecting
    connections from IPs with a history of failed login attemps.
    """
    package_name = 'fail2ban'
    fail2ban_packages = ['fail2ban']
