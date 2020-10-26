Release History
===============

* v1.0.8, October 26, 2020

  * Fix bug where users with periods in their usernames were ignored
  * Pass ``--yes`` to ``gpg`` to auto-confirm removal of private key from key ring during dbrestore process
  * Set ``autostart=true`` for celerybeat and celerycam supervisor processes on worker

* v1.0.7, August 27, 2020

  * Fix bug introduced in 1.0.6 with pre/post tasks running on more hosts than intended

* v1.0.6, August 27, 2020

  * Add hooks to fix pre/post commands for ``bootstrap``, ``reload_production_db``,
    and ``install_rsyslog``
  * Add gunicorn entrypoint script to wait for database connection on launch

* v1.0.5, August 13, 2020

  * Update ``dbrestore`` command to work with Ubuntu 20.04

* v1.0.4, August 12, 2020

  * Minor bug fixes from Python 3 upgrade
  * Reformat the code via Black, Flake8, and isort

* v1.0.3, July 16, 2020

  * Allow customizing where the custom settings file is generated
  * Add celery application name when running celery services
  * Run celery services from code_root rather than project_root

* v1.0.2, July 2, 2020

  * Fix error waiting for autoscaling group to finish restarting.

* v1.0.1, June 22, 2020

  * Minor bug fixes for Python 3 support

* v1.0.0, June 16, 2020

  * Add Python 3 support and drop Python 2 support
