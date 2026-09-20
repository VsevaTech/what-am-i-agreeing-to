"""Generate the synthetic demo agreements in examples/.

All three documents are fictional. They are written with plain ASCII text and no stream
compression so the PDFs stay small, diff-friendly and fully text-extractable.

Usage:  python examples/build_examples.py
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT_DIR = Path(__file__).resolve().parent

# Each document is a list of pages; each page is a list of (kind, text) blocks.
# kind: "h" heading, "p" paragraph.

SIMPLE_SUBSCRIPTION = [
    [
        ("h", "Northwind Fitness Club - Membership Agreement"),
        (
            "p",
            'This Membership Agreement (the "Agreement") is entered into between Northwind '
            'Fitness Club LLC ("Northwind", "we", "us") and the individual identified on the '
            'signature page (the "Member", "you"). This is a synthetic document created for '
            "software testing purposes only. It does not describe a real business.",
        ),
        ("h", "1. Definitions"),
        (
            "p",
            '"Facility" means any Northwind location listed on our website. "Billing Date" means '
            'the calendar day of the month on which your membership started. "Renewal Term" has '
            "the meaning given in Section 4.",
        ),
        ("h", "2. Membership"),
        (
            "p",
            "Your membership entitles you to use the Facility during posted opening hours, attend "
            "group classes subject to availability, and use locker rooms. Guest passes are not "
            "included. Membership is personal and may not be transferred to another person.",
        ),
    ],
    [
        ("h", "3. Fees and Payment"),
        (
            "p",
            "In exchange for membership you agree to pay a membership fee of $29 per month, "
            "charged automatically to the payment method on file on each Billing Date. A one-time "
            "enrollment fee of $49 is charged when this Agreement is signed.",
        ),
        (
            "p",
            "If a payment fails, we will retry the charge up to three times over ten days. A late "
            "payment fee of $10 may be added if the fee remains unpaid fourteen days after the "
            "Billing Date. Fees do not include applicable taxes, which are added where required.",
        ),
        ("h", "3.1 Initial Commitment"),
        (
            "p",
            "This Agreement has an initial commitment period of 6 months starting on the date "
            'you sign (the "Initial Term"). You agree to pay the monthly membership fee for the '
            "full Initial Term even if you stop using the Facility. Early termination during "
            "the Initial Term is only available in the circumstances described in Section 5.3.",
        ),
    ],
    [
        ("h", "4. Automatic Renewal"),
        (
            "p",
            "After the Initial Term, this Agreement automatically renews for successive monthly "
            "periods unless cancelled in accordance with Section 5. Each renewal period is a "
            '"Renewal Term". The monthly fee for each Renewal Term is the fee in effect at the '
            "start of that Renewal Term.",
        ),
        (
            "p",
            "We may change the monthly fee for future Renewal Terms by giving you at least 30 days "
            "written notice by email. If you do not agree to the new fee, you may cancel before "
            "the change takes effect and no new fee will be charged.",
        ),
        ("h", "4.1 Freezing a Membership"),
        (
            "p",
            "You may freeze your membership once per calendar year for one to three months for a "
            "fee of $5 per month. A frozen membership still counts toward the Initial Term.",
        ),
    ],
    [
        ("h", "5. Cancellation"),
        (
            "p",
            "You may cancel this Agreement at any time after the Initial Term. To avoid being "
            "charged for the next Renewal Term, cancellation must be submitted at least 14 days "
            "before the next Billing Date.",
        ),
        (
            "p",
            "Cancellation requests must be made in writing through the member portal or by "
            "email to the address on our website. We will confirm receipt of your request by "
            "email within three business days. Verbal cancellation requests at the front desk "
            "are not accepted.",
        ),
        ("h", "5.3 Early Termination"),
        (
            "p",
            "During the Initial Term you may terminate early only if you move more than 40 km "
            "from the nearest Facility, or if a physician certifies that you are unable to "
            "exercise for more than three months. Proof is required. An early termination fee "
            "equal to one monthly fee applies.",
        ),
        ("h", "6. Refunds"),
        (
            "p",
            "Membership fees already charged are not refunded, except where required by law or "
            "where we are unable to keep the Facility open for more than fourteen consecutive days.",
        ),
    ],
    [
        ("h", "7. Personal Information"),
        (
            "p",
            "We collect your name, contact details, payment details and check-in history to "
            "operate the membership. Personal information may be shared with payment "
            "processors and service providers who help us operate the Facility, such as our "
            "access-control and email vendors. These providers may only use your information to "
            "provide services to us.",
        ),
        (
            "p",
            "We do not sell your personal information. We may disclose information when required "
            "by law. Our full privacy notice is available on our website.",
        ),
        ("h", "8. General"),
        (
            "p",
            "This Agreement is the complete agreement between you and Northwind about your "
            "membership. If any part of it is found unenforceable, the rest remains in effect. "
            "Notices to you will be sent to the email address on file.",
        ),
        ("h", "Signature"),
        (
            "p",
            'By signing below or clicking "I Agree" you confirm that you have read this '
            "Agreement, including the automatic renewal and cancellation terms in Sections 4 and 5.",
        ),
    ],
]

AMBIGUOUS_AGREEMENT = [
    [
        ("h", "Harborline Digital Services - Subscription Terms"),
        (
            "p",
            'These Subscription Terms ("Terms") apply to your use of the Harborline planning '
            'software (the "Service") provided by Harborline Digital Services Ltd ("Harborline"). '
            "This is a synthetic document created for software testing purposes only.",
        ),
        ("h", "1. The Service"),
        (
            "p",
            "Harborline grants you a non-exclusive right to access the Service for your internal "
            "business purposes during the Subscription Period. Features may be added, changed or "
            "removed from time to time.",
        ),
        ("h", "2. Fees"),
        (
            "p",
            "You agree to pay the fees set out in the applicable Order Form or Pricing Schedule. "
            "Fees may vary depending on the plan selected, usage tiers, add-ons and promotional "
            "credits applied to your account. All fees are exclusive of taxes.",
        ),
    ],
    [
        ("h", "3. Subscription Period"),
        (
            "p",
            "The Subscription Period begins on the Effective Date stated in the Order Form and "
            "continues for the period stated there. Unless otherwise agreed, the Subscription "
            "Period may be extended for additional periods on terms to be agreed between the "
            "parties, or as otherwise indicated in your account settings.",
        ),
        ("h", "4. Termination"),
        (
            "p",
            "Either party may terminate these Terms in accordance with Harborline's then-current "
            "cancellation policy, which is available on request. Harborline may suspend or "
            "terminate the Service immediately if you breach these Terms.",
        ),
        ("h", "5. Obligations"),
        (
            "p",
            "You agree to use the Service in compliance with applicable law and these Terms, to "
            "keep your account credentials confidential, and to be responsible for all activity "
            "under your account.",
        ),
        ("h", "6. General"),
        (
            "p",
            "These Terms are governed by the laws stated in the Order Form. Harborline may update "
            "these Terms by posting a new version. Continued use of the Service after an update "
            "constitutes acceptance of the updated Terms.",
        ),
    ],
]

NO_RENEWAL_AGREEMENT = [
    [
        ("h", "Cedar Ridge Workshops - Course Enrollment Agreement"),
        (
            "p",
            'This Course Enrollment Agreement ("Agreement") is between Cedar Ridge Workshops '
            '("Cedar Ridge") and the participant named on the enrollment form ("you"). This is '
            "a synthetic document created for software testing purposes only.",
        ),
        ("h", "1. The Course"),
        (
            "p",
            "You are enrolling in the eight-week evening woodworking course described on the "
            'enrollment form (the "Course"). Materials and use of workshop tools during sessions '
            "are included.",
        ),
        ("h", "2. Course Fee"),
        (
            "p",
            "The Course fee is a one-time payment of $480, due in full at enrollment. There are "
            "no recurring charges under this Agreement.",
        ),
    ],
    [
        ("h", "3. Term and No Renewal"),
        (
            "p",
            "This Agreement covers the single Course you enrolled in and ends when the final "
            "session is completed. This Agreement does not renew automatically. Enrollment in "
            "any future course requires a new enrollment form and a new fee.",
        ),
        ("h", "4. Withdrawal and Refunds"),
        (
            "p",
            "You may withdraw by emailing Cedar Ridge. If you withdraw at least 7 days before the "
            "first session, the fee is refunded in full less a $25 administration charge. No "
            "refund is available after the first session has taken place.",
        ),
        ("h", "5. Your Commitments"),
        (
            "p",
            "You agree to attend sessions on time, follow the safety instructions given by the "
            "instructor, wear eye protection when operating power tools, and pay for any tool "
            "damaged through misuse.",
        ),
        ("h", "6. Personal Information"),
        (
            "p",
            "Cedar Ridge uses your contact details only to administer the Course and does not "
            "share your personal information with third parties, except for the payment "
            "processor that handles your fee payment.",
        ),
    ],
]

DOCUMENTS = {
    "simple-subscription.pdf": SIMPLE_SUBSCRIPTION,
    "ambiguous-agreement.pdf": AMBIGUOUS_AGREEMENT,
    "no-renewal-agreement.pdf": NO_RENEWAL_AGREEMENT,
}


def build(path: Path, pages: list[list[tuple[str, str]]]) -> None:
    c = canvas.Canvas(str(path), pagesize=A4, pageCompression=0, invariant=1)
    c.setTitle(path.stem.replace("-", " ").title())
    c.setAuthor("Synthetic demo document")
    width, height = A4
    margin = 60
    for index, blocks in enumerate(pages, start=1):
        y = height - margin
        for kind, text in blocks:
            if kind == "h":
                y -= 10
                c.setFont("Helvetica-Bold", 13)
                c.drawString(margin, y, text)
                y -= 20
            else:
                c.setFont("Helvetica", 10.5)
                for line in textwrap.wrap(text, 92):
                    c.drawString(margin, y, line)
                    y -= 15
                y -= 8
        c.setFont("Helvetica", 9)
        c.drawString(margin, 30, f"Page {index} of {len(pages)} - synthetic demo document")
        c.showPage()
    c.save()
    # ReportLab writes a 4-byte binary marker comment after the header. Replace it with ASCII of
    # the same length so byte offsets in the xref table stay valid and the file is plain text.
    data = path.read_bytes()
    data = data.replace(b"%\x93\x8c\x8b\x9e", b"%ASCI", 1)
    path.write_bytes(data)


def main() -> None:
    for name, pages in DOCUMENTS.items():
        path = OUT_DIR / name
        build(path, pages)
        data = path.read_bytes()
        assert data.isascii(), f"{name} must be pure ASCII"
        print(f"wrote {path.name} ({len(data)} bytes, {len(pages)} pages)")


if __name__ == "__main__":
    main()
