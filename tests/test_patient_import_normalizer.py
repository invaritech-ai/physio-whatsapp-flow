from app.services.patient_import_normalizer import (
    NORMALIZED_FIELDNAMES,
    SKIPPED_FIELDNAMES,
    normalize_patient_rows,
)


def _row(
    patient_number: str,
    *,
    guid: str,
    first_name: str,
    last_name: str,
    preferred_name: str = "",
    email: str = "",
    mobile: str = "",
    home: str = "",
    work: str = "",
    birth_date: str = "",
    street_1: str = "",
    street_2: str = "",
    city: str = "",
    province: str = "",
    postal: str = "",
    country: str = "",
) -> dict[str, str]:
    return {
        "patient_guid": guid,
        "Patient Number": patient_number,
        "First Name": first_name,
        "Preferred Name": preferred_name,
        "Last Name": last_name,
        "Email": email,
        "Mobile Phone": mobile,
        "Home Phone": home,
        "Work Phone": work,
        "Birth Date": birth_date,
        "Street Address": street_1,
        "Street Address 2": street_2,
        "City": city,
        "Province": province,
        "Postal": postal,
        "Country": country,
    }


def test_normalize_patient_rows_applies_user_canonical_rules():
    normalized_rows, skipped_rows = normalize_patient_rows(
        [
            _row(
                "7",
                guid="84029-7",
                first_name="Harry Hoi Leuk",
                last_name="Fung",
                email="harryfung8@hotmail.com",
                mobile="+85263121852",
                home="+85263121852",
                birth_date="1977-11-07",
                city="Sai Ying Pun",
                province="Hong Kong Island",
                country="HK",
            ),
            _row(
                "22",
                guid="84029-22",
                first_name="Harry",
                last_name="Fung",
                email="harry.fung@movementfitnesshk.com",
                mobile="+85263121852",
            ),
            _row(
                "19",
                guid="84029-19",
                first_name="Vincent",
                last_name="Kwok",
                mobile="+85295480821",
                city="Sai Ying Pun",
                province="Hong Kong Island",
                country="HK",
            ),
            _row(
                "20",
                guid="84029-20",
                first_name="Vincent",
                last_name="Kwok",
                mobile="+85295480821",
            ),
            _row(
                "8",
                guid="84029-8",
                first_name="May Yan",
                last_name="Chow",
                email="serena6chow@gmail.com",
                home="+85298215602",
                city="Sai Ying Pun",
                province="Hong Kong Island",
                country="HK",
            ),
            _row(
                "63",
                guid="84029-64",
                first_name="ying",
                last_name="cheng",
                email="cytwstudy@gmail.com",
            ),
            _row(
                "2",
                guid="84029-2",
                first_name="Lo",
                last_name="Cheung",
                mobile="+85295559318",
            ),
            _row(
                "30",
                guid="84029-30",
                first_name="Ka Ying",
                last_name="Ng",
                mobile="+85295559318",
            ),
        ]
    )

    assert NORMALIZED_FIELDNAMES == [
        "id",
        "phone_e164",
        "name",
        "email",
        "date_of_birth",
        "address",
        "conversation_state",
        "preferred_therapist_id",
        "default_receipt_amount_cents",
    ]
    assert SKIPPED_FIELDNAMES == [
        "patient_number",
        "patient_guid",
        "name",
        "chosen_phone",
        "skip_reason",
    ]

    assert normalized_rows == [
        {
            "id": "7",
            "phone_e164": "+85263121852",
            "name": "Harry Hoi Leuk Fung",
            "email": "harryfung8@hotmail.com",
            "date_of_birth": "1977-11-07",
            "address": "Sai Ying Pun, Hong Kong Island, HK",
            "conversation_state": "IDLE",
            "preferred_therapist_id": "",
            "default_receipt_amount_cents": "",
        },
        {
            "id": "19",
            "phone_e164": "+85295480821",
            "name": "Vincent Kwok",
            "email": "",
            "date_of_birth": "",
            "address": "Sai Ying Pun, Hong Kong Island, HK",
            "conversation_state": "IDLE",
            "preferred_therapist_id": "",
            "default_receipt_amount_cents": "",
        },
        {
            "id": "8",
            "phone_e164": "+85298215602",
            "name": "May Yan Chow",
            "email": "serena6chow@gmail.com",
            "date_of_birth": "",
            "address": "Sai Ying Pun, Hong Kong Island, HK",
            "conversation_state": "IDLE",
            "preferred_therapist_id": "",
            "default_receipt_amount_cents": "",
        },
    ]
    assert skipped_rows == [
        {
            "patient_number": "22",
            "patient_guid": "84029-22",
            "name": "Harry Fung",
            "chosen_phone": "+85263121852",
            "skip_reason": "duplicate_phone_non_canonical",
        },
        {
            "patient_number": "20",
            "patient_guid": "84029-20",
            "name": "Vincent Kwok",
            "chosen_phone": "+85295480821",
            "skip_reason": "duplicate_phone_non_canonical",
        },
        {
            "patient_number": "63",
            "patient_guid": "84029-64",
            "name": "ying cheng",
            "chosen_phone": "",
            "skip_reason": "missing_phone",
        },
        {
            "patient_number": "2",
            "patient_guid": "84029-2",
            "name": "Lo Cheung",
            "chosen_phone": "+85295559318",
            "skip_reason": "duplicate_phone_excluded_cluster",
        },
        {
            "patient_number": "30",
            "patient_guid": "84029-30",
            "name": "Ka Ying Ng",
            "chosen_phone": "+85295559318",
            "skip_reason": "duplicate_phone_excluded_cluster",
        },
    ]


def test_normalize_patient_rows_combines_sparse_address_fields():
    normalized_rows, skipped_rows = normalize_patient_rows(
        [
            _row(
                "31",
                guid="84029-31",
                first_name="Joseph",
                last_name="Lee",
                home="+447511404108",
                street_1="15D Kenyon Court",
                street_2="48-50 Bonham Road",
                city="Sai Ying Pun",
                country="HK",
            )
        ]
    )

    assert skipped_rows == []
    assert normalized_rows == [
        {
            "id": "31",
            "phone_e164": "+447511404108",
            "name": "Joseph Lee",
            "email": "",
            "date_of_birth": "",
            "address": "15D Kenyon Court, 48-50 Bonham Road, Sai Ying Pun, HK",
            "conversation_state": "IDLE",
            "preferred_therapist_id": "",
            "default_receipt_amount_cents": "",
        }
    ]
