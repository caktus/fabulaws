from fabric.api import *
from fabric.contrib import files

class ShorewallMixin(object):
    """
    FabulAWS Ubuntu mixin that installs and configures the Shorewall firewall
    """
    shorewall_open_ports = ['SSH']

    def setup(self):
        """
        Hooks into the FabulAWS setup process to configure Shorewall on the
        server.
        """
        super(ShorewallMixin, self).setup()
        with self:
            self._setup_firewall()

    def _setup_firewall(self):
        """
        Configures and starts up a Shorewall firewall on the remote server.
        """
        sudo('apt-get install -y shorewall')
        rules = '\n'.join(['{0}/ACCEPT\tnet\t\t$FW'.format(p)
                           for p in self.shorewall_open_ports])
        with cd('/etc/shorewall'):
            sudo('rsync -a /usr/share/doc/shorewall/examples/one-interface/ .')
            if files.exists('shorewall.conf.gz'):
                sudo('gunzip -f shorewall.conf.gz')
            files.append('rules', rules, use_sudo=True)
            sudo('sed -i "s/STARTUP_ENABLED=No/STARTUP_ENABLED=Yes/" shorewall.conf')
        sudo('shorewall start')
