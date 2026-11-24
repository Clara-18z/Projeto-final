from datetime import date


PRIORITY_CATEGORIES = {
    "pessoa_com_deficiencia": "Pessoa com deficiência",
    "pessoa_com_tea": "Pessoa com TEA",
    "idoso_60_mais": "Pessoa idosa (60 anos ou mais)",
    "gestante": "Gestante",
    "lactante": "Lactante",
    "crianca_de_colo": "Pessoa com criança de colo",
    "pessoa_obesa": "Pessoa obesa",
    "mobilidade_reduzida": "Pessoa com mobilidade reduzida",
    "doador_de_sangue": "Doador de sangue",
}

BLOOD_DONATION_VALIDITY_DAYS = 120


def validate_priority_registration(category, evidence_checked, donation_date, today=None):
    if category not in PRIORITY_CATEGORIES:
        return "Selecione uma categoria de prioridade válida."
    if not evidence_checked:
        return "Confirme a verificação administrativa da comprovação necessária."
    if category != "doador_de_sangue":
        if donation_date is not None:
            return "A data de doação só se aplica à categoria de doador de sangue."
        return None

    if donation_date is None:
        return "Informe a data da doação de sangue."
    today = today or date.today()
    age_days = (today - donation_date).days
    if age_days < 0 or age_days > BLOOD_DONATION_VALIDITY_DAYS:
        return "O comprovante de doação deve ter no máximo 120 dias."
    return None


def priority_label(category):
    return PRIORITY_CATEGORIES.get(category, "Categoria inválida")
