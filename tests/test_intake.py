from email.message import EmailMessage

import pytest

from photo_hub.intake import IntakeError, parse_destination, parse_submission


def test_parse_destination_from_subject_or_body():
    assert parse_destination("both family photo", "") == "both"
    assert parse_destination("", "tv\nhello") == "tv"
    assert parse_destination("FRAME:", "") == "frame"


def test_parse_destination_rejects_ambiguity():
    with pytest.raises(IntakeError, match="ambiguous"):
        parse_destination("frame", "tv")


def test_parse_submission_accepts_one_authorized_image():
    message = EmailMessage()
    message["From"] = "User <you@example.com>"
    message["Subject"] = "both"
    message.set_content("for the frames")
    message.add_attachment(b"fake-jpeg", maintype="image", subtype="jpeg", filename="photo.jpg")

    submission = parse_submission(message, ["you@example.com"], 100)
    assert submission.sender == "you@example.com"
    assert submission.destination == "both"
    assert submission.attachment.filename == "photo.jpg"


def test_parse_submission_rejects_unauthorized_sender():
    message = EmailMessage()
    message["From"] = "other@example.com"
    message["Subject"] = "frame"
    message.set_content("x")
    message.add_attachment(b"fake-jpeg", maintype="image", subtype="jpeg", filename="photo.jpg")

    with pytest.raises(IntakeError, match="not authorized"):
        parse_submission(message, ["you@example.com"], 100)


def test_parse_submission_requires_exactly_one_image():
    message = EmailMessage()
    message["From"] = "you@example.com"
    message["Subject"] = "frame"
    message.set_content("x")

    with pytest.raises(IntakeError, match="exactly one"):
        parse_submission(message, ["you@example.com"], 100)
