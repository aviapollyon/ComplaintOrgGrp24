# Import all models here so Flask-Migrate can detect them
from app.models.department import Department      # noqa: F401
from app.models.user import User                  # noqa: F401
from app.models.ticket import Ticket              # noqa: F401
from app.models.ticket_update import TicketUpdate # noqa: F401
from app.models.attachment import Attachment      # noqa: F401