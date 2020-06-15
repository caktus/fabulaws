from mock import patch

from .utils import unittest, ArgyleTest
from argyle import rabbitmq


class RabbitTest(ArgyleTest):
    "Base for setting up necessary patches."

    package = 'argyle.rabbitmq'
    patched_commands = ['sudo', 'upload_template', 'restart_service', ]


class RabbitCommandsTest(RabbitTest):
    "Common rabbitmqctl commands for creating users/vhosts."

    def test_create_user(self):
        "Create a RabbitMQ user."
        rabbitmq.create_user('foo', 'bar')
        self.assertSudoCommand('rabbitmqctl add_user foo bar')

    def test_create_vhost(self):
        "Create a RabbitMQ vhost."
        rabbitmq.create_vhost('baz')
        self.assertSudoCommand('rabbitmqctl add_vhost baz')

    def test_set_default_permissions(self):
        "Grant use all permssions on a given vhost."
        rabbitmq.set_vhost_permissions(vhost='baz', username='foo')
        self.assertSudoCommand('rabbitmqctl set_permissions -p baz foo ".*" ".*" ".*"')

    def test_set_custom_permissions(self):
        "Grant permissions other than the default."
        rabbitmq.set_vhost_permissions(vhost='baz', username='foo', permissions='".*" "^amq.gen.*$" ".*"')
        self.assertSudoCommand('rabbitmqctl set_permissions -p baz foo ".*" "^amq.gen.*$" ".*"')


class RabbitEnvironmentTest(RabbitTest):
    "Configuration upload for rabbitmq-env.conf."

    def test_default_conf(self):
        "Upload default rabbitmq-env.conf."
        rabbitmq.upload_rabbitmq_environment_conf()
        # No additional context by default
        self.assertTemplateContext(None)
        self.assertTemplateUsed(u'rabbitmq/rabbitmq-env.conf')
        self.assertTemplateDesination(u'/etc/rabbitmq/rabbitmq-env.conf')
        # RabbitMQ restarted by default
        self.assertTrue(self.mocks['restart_service'].called)

    def test_alternate_template(self):
        "Using a different template does not change the destination."
        rabbitmq.upload_rabbitmq_environment_conf(u'rabbit/foo.conf')
        self.assertTemplateUsed(u'rabbit/foo.conf')
        self.assertTemplateDesination(u'/etc/rabbitmq/rabbitmq-env.conf')

    def test_additional_context(self):
        "Additional context can be passed to the template."
        rabbitmq.upload_rabbitmq_environment_conf(context={'foo': 'bar'})
        self.assertTemplateContext({'foo': 'bar'})

    def test_no_restart(self):
        "Upload new configuration without a restart."
        rabbitmq.upload_rabbitmq_environment_conf(restart=False)
        self.assertFalse(self.mocks['restart_service'].called)


class RabbitConfigTest(RabbitTest):
    "Configuration upload for rabbitmq.config."

    def test_default_conf(self):
        "Upload default rabbitmq.config."
        rabbitmq.upload_rabbitmq_conf()
        # No additional context by default
        self.assertTemplateContext(None)
        self.assertTemplateUsed(u'rabbitmq/rabbitmq.config')
        self.assertTemplateDesination(u'/etc/rabbitmq/rabbitmq.config')
        # RabbitMQ restarted by default
        self.assertTrue(self.mocks['restart_service'].called)

    def test_alternate_template(self):
        "Using a different template does not change the destination."
        rabbitmq.upload_rabbitmq_conf(u'rabbit/foo.conf')
        self.assertTemplateUsed(u'rabbit/foo.conf')
        self.assertTemplateDesination(u'/etc/rabbitmq/rabbitmq.config')

    def test_additional_context(self):
        "Additional context can be passed to the template."
        rabbitmq.upload_rabbitmq_conf(context={'foo': 'bar'})
        self.assertTemplateContext({'foo': 'bar'})

    def test_no_restart(self):
        "Upload new configuration without a restart."
        rabbitmq.upload_rabbitmq_conf(restart=False)
        self.assertFalse(self.mocks['restart_service'].called)


if __name__ == '__main__':
    unittest.main()
