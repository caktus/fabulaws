from fabric.api import *
from fabric.contrib import files

from fabulaws.decorators import uses_fabric

class ShorewallMixin(object):
    """
    FabulAWS Ubuntu mixin that installs and configures the Shorewall firewall
    """
    shorewall_open_ports = ['SSH']
    shorewall_custom = []

    def setup(self):
        """
        Hooks into the FabulAWS setup process to configure Shorewall on the
        server.
        """
        super(ShorewallMixin, self).setup()
        self._setup_firewall()

    @uses_fabric
    def _setup_firewall(self):
        """
        Configures and starts up a Shorewall firewall on the remote server.
        """
        sudo('apt-get install -y shorewall')
        rules = ['{0}/ACCEPT net $FW'.format(p)
                 for p in self.shorewall_open_ports]
        rules.extend(self.shorewall_custom)
        with cd('/etc/shorewall'):
            sudo('rsync -a /usr/share/doc/shorewall/examples/one-interface/ .')
            if files.exists('shorewall.conf.gz'):
                sudo('gunzip -f shorewall.conf.gz')
            files.append('rules', '\n'.join(rules), use_sudo=True)
            sudo('sed -i "s/STARTUP_ENABLED=No/STARTUP_ENABLED=Yes/" shorewall.conf')
        sudo('shorewall start')
