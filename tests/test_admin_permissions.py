from handlers.admin_handlers import MUTE_PERMISSIONS, UNMUTE_PERMISSIONS

# Every chat permission the bot toggles on mute/unmute. Keeping this list
# explicit makes the test fail loudly if PTB adds a new permission field that
# the two objects forget to handle symmetrically.
PERMISSION_FIELDS = (
    "can_send_messages",
    "can_send_audios",
    "can_send_documents",
    "can_send_photos",
    "can_send_videos",
    "can_send_video_notes",
    "can_send_voice_notes",
    "can_send_polls",
    "can_send_other_messages",
    "can_add_web_page_previews",
    "can_change_info",
    "can_invite_users",
    "can_pin_messages",
)


def test_mute_disables_every_permission():
    for field in PERMISSION_FIELDS:
        assert getattr(MUTE_PERMISSIONS, field) is False, field


def test_unmute_restores_every_permission():
    for field in PERMISSION_FIELDS:
        assert getattr(UNMUTE_PERMISSIONS, field) is True, field


def test_mute_and_unmute_cover_the_same_fields():
    # Unset ChatPermissions fields default to None; both objects must set the
    # exact same set of fields so /unmute always cancels /mute symmetrically.
    mute_set = {f for f in PERMISSION_FIELDS if getattr(MUTE_PERMISSIONS, f) is not None}
    unmute_set = {f for f in PERMISSION_FIELDS if getattr(UNMUTE_PERMISSIONS, f) is not None}
    assert mute_set == unmute_set == set(PERMISSION_FIELDS)
