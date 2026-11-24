PERMISSION_DEFINITIONS = (
    ("acessar_dashboard", "Acesso ao dashboard"),
    ("gerenciar_usuarios", "Gerenciar usuários"),
    ("gerenciar_medicos", "Gerenciar médicos, especialidades e salas"),
    ("gerenciar_pacientes", "Gerenciar pacientes"),
    ("consultar_servicos", "Consultar serviços e preços"),
    ("gerenciar_servicos", "Gerenciar serviços e preços"),
    ("gerenciar_solicitacoes", "Gerenciar solicitações"),
    ("gerenciar_agenda", "Gerenciar agenda e agendamentos"),
    ("gerenciar_fila", "Acompanhar e operar fila"),
    ("gerenciar_atendimento", "Gerenciar atendimento médico"),
    ("gerenciar_financeiro", "Operar caixa e validar pagamentos"),
    ("consultar_relatorios", "Consultar relatórios operacionais"),
    ("consultar_auditoria", "Consultar trilha de auditoria"),
)

ADMIN_RESTRICTED_PERMISSIONS = frozenset(
    {
        "gerenciar_solicitacoes",
        "gerenciar_agenda",
        "gerenciar_fila",
        "gerenciar_pacientes",
        "gerenciar_financeiro",
    }
)

PROFILE_PERMISSIONS = {
    "administrador": frozenset(
        code
        for code, _ in PERMISSION_DEFINITIONS
        if code not in ADMIN_RESTRICTED_PERMISSIONS
    ),
    "recepcionista": frozenset(
        {
            "acessar_dashboard",
            "gerenciar_pacientes",
            "gerenciar_solicitacoes",
            "gerenciar_agenda",
            "gerenciar_fila",
        }
    ),
    "medico": frozenset(
        {
            "acessar_dashboard",
            "gerenciar_agenda",
            "gerenciar_atendimento",
        }
    ),
    "financeiro": frozenset(
        {
            "acessar_dashboard",
            "gerenciar_financeiro",
            "consultar_servicos",
        }
    ),
}

PROFILE_CHOICES = (
    ("recepcionista", "Recepcionista"),
    ("medico", "Médico"),
    ("financeiro", "Financeiro"),
    ("administrador", "Administrador"),
)

PROFILE_PERMISSION_OPTIONS = {
    profile: sorted(codes) for profile, codes in PROFILE_PERMISSIONS.items()
}


def has_permission(user, permission_codes):
    if isinstance(permission_codes, str):
        permission_codes = {permission_codes}
    assigned_codes = {permission.codigo for permission in user.permissoes}
    return bool(assigned_codes.intersection(permission_codes))


def has_profile_permission(user, profiles, permission_codes):
    if isinstance(profiles, str):
        profiles = {profiles}
    return user.perfil in profiles and has_permission(user, permission_codes)


def permissions_for_profile(profile):
    return PROFILE_PERMISSIONS.get(profile, frozenset())
