from functools import wraps

from fabulaws.ec2 import EC2Instance


def uses_fabric(f):
    @wraps(f)
    def wrapper(self, *args, **kwds):
        if not isinstance(self, EC2Instance):
            raise ValueError('@uses_fabric can only wrap methods on '
                             'ECInstance classes')
        with self:
            return f(self, *args, **kwds)
    return wrapper
