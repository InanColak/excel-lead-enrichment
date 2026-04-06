from app.models.base import Base

# Import model modules to register them with Base.metadata for Alembic autogenerate.
# Use module-level imports (not class-level) to avoid circular import issues
# when model files import from app.models.base.
import app.auth.models as _auth_models  # noqa: F401, E402
import app.admin.models as _admin_models  # noqa: F401, E402
import app.contacts.models as _contacts_models  # noqa: F401, E402

__all__ = ["Base"]
