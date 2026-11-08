"""Previous import path for the private-video whitelist.

``VideoAllowedUser`` in ``app.models.access`` is the mapped class.
``VideoAccess`` is the same class under the name used by earlier code.
"""

from app.models.access import VideoAllowedUser as VideoAccess

__all__ = ["VideoAccess"]
