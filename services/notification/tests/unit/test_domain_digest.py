import pytest

from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import BusinessId, TenantId
from notification.domain.digest import SummaryItem, compose, join_lines, summary_key
from notification.domain.ids import RecipientId
from notification.domain.policy import BatchPolicy
from notification.domain.recipients import BusinessLink, DigestMode, Recipient, RecipientRole
from notification.domain.templates import find_template, render
from notification.testing import NOON_IST

ACME = BusinessId.new()
BETA = BusinessId.new()
KEY = DedupeKey("a" * 64)


def recipient(role: RecipientRole = RecipientRole.OWNER, **changes: object) -> Recipient:
    values: dict[str, object] = {
        "id": RecipientId.new(),
        "tenant_id": TenantId.new(),
        "user_id": None,
        "role": role,
        "businesses": (BusinessLink(ACME, "Acme Traders"), BusinessLink(BETA, "Beta Foods")),
        "created_at": NOON_IST,
        "updated_at": NOON_IST,
    }
    values.update(changes)
    return Recipient(**values)  # type: ignore[arg-type]


def due(title: str, business: BusinessId = ACME) -> SummaryItem:
    return SummaryItem(business, "obligation_due_soon", {"title": title, "due_date": "20 Oct"})


def test_a_batch_for_one_business_lists_one_line_per_notification() -> None:
    items = [
        due("File GSTR-1"),
        SummaryItem(ACME, "obligation_closed", {"title": "File CMP-08"}),
        SummaryItem(ACME, "change_card", {"title": "Display the certificate"}),
    ]
    whatsapp = compose(items, Channel.WHATSAPP, recipient())
    assert whatsapp.template_key == "batch_summary"
    assert whatsapp.params == {
        "count": 3,
        "client_count": 1,
        "business_name": "Acme Traders",
        "lines": "Due 20 Oct - File GSTR-1; Closed - File CMP-08; New - Display the certificate",
    }
    email = compose(items, Channel.EMAIL, recipient())
    assert email.params["lines"] == (
        "Due 20 Oct - File GSTR-1\nClosed - File CMP-08\nNew - Display the certificate"
    )


def test_whatsapp_lines_never_carry_a_newline() -> None:
    items = [SummaryItem(ACME, "obligation_closed", {"title": "File\nGSTR-1\t  now"}), due("B")]
    composed = compose(items, Channel.WHATSAPP, recipient())
    lines = str(composed.params["lines"])
    assert "\n" not in lines
    assert "\t" not in lines
    assert lines == "Closed - File GSTR-1 now; Due 20 Oct - B"
    message = render(
        composed.template_key,
        Channel.WHATSAPP,
        "en",
        {**composed.params, "link": "https://app.example/obligations"},
        recipient="+919876543210",
        dedupe_key=KEY,
    )
    assert "Changes to your compliance calendar: 2." in message.body


def test_a_long_list_ends_in_and_n_more() -> None:
    items = [due(f"Return {n}") for n in range(15)]
    by_count = compose(items, Channel.WHATSAPP, recipient(), policy=BatchPolicy(max_lines=3))
    assert by_count.params["lines"] == (
        "Due 20 Oct - Return 0; Due 20 Oct - Return 1; Due 20 Oct - Return 2; and 12 more"
    )
    assert by_count.params["count"] == 15
    by_size = compose(items, Channel.WHATSAPP, recipient(), policy=BatchPolicy(max_param_chars=60))
    text = str(by_size.params["lines"])
    assert text == "Due 20 Oct - Return 0; Due 20 Oct - Return 1; and 13 more"
    assert len(text) <= 60
    hindi = compose(
        items, Channel.EMAIL, recipient(), language="hi", policy=BatchPolicy(max_lines=1)
    )
    assert str(hindi.params["lines"]).endswith("\nऔर 14 अन्य")


def test_a_line_longer_than_the_limit_is_cut_short() -> None:
    policy = BatchPolicy(max_param_chars=40)
    alone = join_lines(["x" * 100], "; ", lambda n: f"and {n} more", policy)
    assert alone == "x" * 37 + "..."
    with_tail = join_lines(["y" * 100, "z"], "; ", lambda n: f"and {n} more", policy)
    assert with_tail.endswith("...; and 1 more")
    assert len(with_tail) <= 40


def test_ca_firms_get_the_client_digest_and_owners_the_daily_one() -> None:
    items = [due("File GSTR-1"), due("File GSTR-3B", BETA)]
    ca = compose(
        items,
        Channel.WHATSAPP,
        recipient(RecipientRole.CA_STAFF, org_label="Rao & Co"),
        digest=True,
    )
    assert ca.template_key == "ca_digest"
    assert ca.params == {
        "count": 2,
        "client_count": 2,
        "org_label": "Rao & Co",
        "lines": "Acme Traders: Due 20 Oct - File GSTR-1; Beta Foods: Due 20 Oct - File GSTR-3B",
    }
    unnamed = compose(items, Channel.WHATSAPP, recipient(RecipientRole.CA_ADMIN), digest=True)
    assert unnamed.params["org_label"] == "your firm"
    owner = recipient(digest_mode=DigestMode.DAILY)
    assert compose(items, Channel.EMAIL, owner, digest=True).template_key == "daily_digest"
    assert summary_key(owner, digest=False) == "batch_summary"
    for composed in (ca, compose(items, Channel.EMAIL, owner, digest=True)):
        template = find_template(composed.template_key, Channel.WHATSAPP, "en")
        assert set(template.placeholders) <= {*composed.params, "link"}


def test_a_batch_across_businesses_labels_its_lines() -> None:
    items = [due("A"), due("B", BETA), due("C", BusinessId.new())]
    composed = compose(items, Channel.WHATSAPP, recipient(language="hi"))
    assert composed.params["business_name"] == "आपके व्यवसाय"
    assert composed.params["client_count"] == 3
    assert composed.params["lines"] == (
        "Acme Traders: अंतिम तिथि 20 Oct - A; Beta Foods: अंतिम तिथि 20 Oct - B; अंतिम तिथि 20 Oct - C"
    )
    unlabelled = compose([due("A")], Channel.WHATSAPP, recipient(businesses=()))
    assert unlabelled.params["business_name"] == "your business"


def test_a_line_without_its_values_falls_back_to_the_title_or_the_key() -> None:
    items = [
        SummaryItem(ACME, "obligation_due_soon", {"title": "No date"}),
        SummaryItem(ACME, "manual_template", {}),
    ]
    assert compose(items, Channel.WHATSAPP, recipient()).params["lines"] == (
        "No date; manual_template"
    )


def test_a_summary_needs_notifications() -> None:
    with pytest.raises(InvariantViolationError):
        compose([], Channel.WHATSAPP, recipient())
    with pytest.raises(InvariantViolationError):
        BatchPolicy(max_param_chars=10)
    assert BatchPolicy(window_seconds=120).window.total_seconds() == 120
