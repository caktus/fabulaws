from fabric.api import *
from fabric.contrib import files

from fabulaws.decorators import uses_fabric
from fabulaws.ubuntu.packages.base import AptMixin

class ShorewallMixin(AptMixin):
    """
    FabulAWS Ubuntu mixin that installs and configures the Shorewall firewall
    """
    package_name = 'shorewall'
    shorewall_packages = ['shorewall']
    shorewall_open_ports = ['SSH']
    shorewall_custom = []
    shorewall_allow_icmp = False

    def _get_rules(self, ports):
        for p in ports:
            try:
                p = int(p)
                yield 'ACCEPT net $FW tcp {0}'.format(p)
            except ValueError:
                # looks like a macro, use this format instead
                yield '{0}/ACCEPT net $FW'.format(p)

    @uses_fabric
    def _setup_firewall(self):
        """
        Configures and starts up a Shorewall firewall on the remote server.
        """
        rules = list(self._get_rules(self.shorewall_open_ports))
        rules.extend(self.shorewall_custom)
        with cd('/etc/shorewall'):
            sudo('rsync -a /usr/share/doc/shorewall/examples/one-interface/ .')
            if files.exists('shorewall.conf.gz'):
                sudo('gunzip -f shorewall.conf.gz')
            files.append('rules', '\n'.join(rules), use_sudo=True)
            sudo('sed -i "s/STARTUP_ENABLED=No/STARTUP_ENABLED=Yes/" shorewall.conf')
        if self.shorewall_allow_icmp:
            files.sed('/etc/shorewall/rules', r'Ping\(DROP\)',
                      'Ping(ACCEPT)', use_sudo=True)
        sudo('shorewall start')

    def setup(self):
        """
        Hooks into the FabulAWS setup process to configure Shorewall on the
        server.
        """
        super(ShorewallMixin, self).setup()
        self._setup_firewall()
