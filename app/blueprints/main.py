"""대시보드: 내 캠페인 요약 + 최근 캠페인 + 공지."""
from flask import Blueprint, g, render_template

from ..constants import CHANNEL_LABEL, STATUS_CLASS, STATUS_LABEL
from ..models import campaign as campaign_model
from ..models import content as content_model

bp = Blueprint("main", __name__)


def render_placeholder(title, phase=None, desc=None):
    """아직 준비되지 않은 라우트용 공용 페이지."""
    return render_template("placeholder.html", title=title, phase_label=None, desc=desc)


@bp.route("/")
def dashboard():
    uid = g.user["id"]
    counts = campaign_model.status_counts(uid, "store")
    recent = campaign_model.list_recent_channel(uid, "store", 8)
    notices = content_model.dashboard_notices(5)
    return render_template("main/dashboard.html", counts=counts, recent=recent, notices=notices,
                           channel_label=CHANNEL_LABEL, status_label=STATUS_LABEL, status_class=STATUS_CLASS)
