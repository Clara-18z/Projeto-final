from datetime import datetime
import re

from flask_login import UserMixin
from sqlalchemy import CheckConstraint, Index, UniqueConstraint

from database import db


usuario_permissoes = db.Table(
    "usuario_permissoes",
    db.Column("usuario_id", db.Integer, db.ForeignKey("usuarios.id"), primary_key=True),
    db.Column("permissao_id", db.Integer, db.ForeignKey("permissoes.id"), primary_key=True),
)


class Usuario(UserMixin, db.Model):
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    nome_completo = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    senha_hash = db.Column(db.String(255), nullable=False)
    perfil = db.Column(db.String(40), nullable=False, default="recepcionista")
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    ultimo_login = db.Column(db.DateTime, nullable=True)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    permissoes = db.relationship("Permissao", secondary=usuario_permissoes, back_populates="usuarios")
    medico = db.relationship("Medico", back_populates="usuario", uselist=False)
    registros_auditoria = db.relationship("RegistroAuditoria", back_populates="usuario")
    historico_status = db.relationship("HistoricoStatus", back_populates="usuario")


class Permissao(db.Model):
    __tablename__ = "permissoes"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(80), unique=True, nullable=False)
    nome = db.Column(db.String(100), nullable=False)
    descricao = db.Column(db.Text, nullable=True)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    usuarios = db.relationship("Usuario", secondary=usuario_permissoes, back_populates="permissoes")


class Paciente(db.Model):
    __tablename__ = "pacientes"

    id = db.Column(db.Integer, primary_key=True)
    nome_completo = db.Column(db.String(150), nullable=False)
    cpf = db.Column(db.String(11), unique=True, nullable=False)
    data_nascimento = db.Column(db.Date, nullable=False)
    telefone = db.Column(db.String(20), nullable=False)
    endereco = db.Column(db.Text, nullable=False)
    email = db.Column(db.String(150), nullable=True)
    observacoes = db.Column(db.Text, nullable=True)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    solicitacoes = db.relationship("Solicitacao", back_populates="paciente")
    agendamentos = db.relationship("Agendamento", back_populates="paciente")
    senhas = db.relationship("Senha", back_populates="paciente")
    atendimentos = db.relationship("Atendimento", back_populates="paciente")

    @staticmethod
    def normalize_cpf(value):
        if not value:
            return value
        return re.sub(r"\D", "", value)

    @property
    def cpf_formatado(self):
        return self.cpf[:3] + "." + self.cpf[3:6] + "." + self.cpf[6:9] + "-" + self.cpf[9:11] if len(self.cpf) == 11 else self.cpf


class Especialidade(db.Model):
    __tablename__ = "especialidades"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), unique=True, nullable=False)
    descricao = db.Column(db.Text, nullable=True)
    ativa = db.Column(db.Boolean, nullable=False, default=True)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    medicos = db.relationship("Medico", back_populates="especialidade")
    servicos = db.relationship("Servico", back_populates="especialidade")
    solicitacoes = db.relationship("Solicitacao", back_populates="especialidade")


class Medico(db.Model):
    __tablename__ = "medicos"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), unique=True, nullable=False)
    especialidade_id = db.Column(db.Integer, db.ForeignKey("especialidades.id"), nullable=False)
    sala_id = db.Column(db.Integer, db.ForeignKey("salas.id"), nullable=True)
    crm = db.Column(db.String(30), unique=True, nullable=False)
    nome_exibicao = db.Column(db.String(100), nullable=False)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    status = db.Column(db.String(30), nullable=False, default="disponivel")
    presenca_ativa = db.Column(db.Boolean, nullable=False, default=False)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    usuario = db.relationship("Usuario", back_populates="medico")
    especialidade = db.relationship("Especialidade", back_populates="medicos")
    sala = db.relationship("Sala", back_populates="medicos")
    disponibilidades = db.relationship("DisponibilidadeMedica", back_populates="medico")
    agendamentos = db.relationship("Agendamento", back_populates="medico")
    senhas = db.relationship("Senha", back_populates="medico")
    atendimentos = db.relationship("Atendimento", back_populates="medico")

    __table_args__ = (
        Index("uq_medicos_sala_id", "sala_id", unique=True),
    )


class Sala(db.Model):
    __tablename__ = "salas"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(80), unique=True, nullable=False)
    setor = db.Column(db.String(80), nullable=False, default="consulta")
    status = db.Column(db.String(30), nullable=False, default="disponivel")
    ativa = db.Column(db.Boolean, nullable=False, default=True)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    medicos = db.relationship("Medico", back_populates="sala")
    agendamentos = db.relationship("Agendamento", back_populates="sala")
    senhas = db.relationship("Senha", back_populates="sala")
    atendimentos = db.relationship("Atendimento", back_populates="sala")


class Servico(db.Model):
    __tablename__ = "servicos"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), unique=True, nullable=False)
    categoria = db.Column(db.String(40), nullable=False)
    descricao = db.Column(db.Text, nullable=True)
    valor = db.Column(db.Float, nullable=False, default=0.0)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    especialidade_id = db.Column(db.Integer, db.ForeignKey("especialidades.id"), nullable=False)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    especialidade = db.relationship("Especialidade", back_populates="servicos")
    solicitacoes = db.relationship("Solicitacao", back_populates="servico")

    __table_args__ = (
        CheckConstraint("valor >= 0", name="check_servico_valor_positivo"),
    )


class Solicitacao(db.Model):
    __tablename__ = "solicitacoes"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(30), unique=True, nullable=False)
    paciente_id = db.Column(db.Integer, db.ForeignKey("pacientes.id"), nullable=False)
    servico_id = db.Column(db.Integer, db.ForeignKey("servicos.id"), nullable=False)
    especialidade_id = db.Column(db.Integer, db.ForeignKey("especialidades.id"), nullable=True)
    medico_id = db.Column(db.Integer, db.ForeignKey("medicos.id"), nullable=True)
    valor_snapshot = db.Column(db.Float, nullable=False, default=0.0)
    status = db.Column(db.String(30), nullable=False, default="aguardando_pagamento")
    data_solicitacao = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    observacoes = db.Column(db.Text, nullable=True)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    paciente = db.relationship("Paciente", back_populates="solicitacoes")
    servico = db.relationship("Servico", back_populates="solicitacoes")
    especialidade = db.relationship("Especialidade", back_populates="solicitacoes")
    medico = db.relationship("Medico", backref="solicitacoes")
    documentos = db.relationship("DocumentoSolicitacao", back_populates="solicitacao")
    confirmacao_pagamento = db.relationship("ConfirmacaoPagamento", back_populates="solicitacao", uselist=False)
    validacao_pagamento = db.relationship(
        "ValidacaoPagamentoFinanceiro",
        back_populates="solicitacao",
        uselist=False,
    )
    agendamento = db.relationship("Agendamento", back_populates="solicitacao", uselist=False)
    historico_status = db.relationship("HistoricoStatus", back_populates="solicitacao")


class DocumentoSolicitacao(db.Model):
    __tablename__ = "documentos_solicitacao"

    id = db.Column(db.Integer, primary_key=True)
    solicitacao_id = db.Column(db.Integer, db.ForeignKey("solicitacoes.id"), nullable=False)
    tipo = db.Column(db.String(50), nullable=False)
    nome_arquivo = db.Column(db.String(200), nullable=False)
    caminho_arquivo = db.Column(db.String(255), nullable=False)
    data_emissao = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    solicitacao = db.relationship("Solicitacao", back_populates="documentos")


class ConfirmacaoPagamento(db.Model):
    __tablename__ = "confirmacoes_pagamento"

    id = db.Column(db.Integer, primary_key=True)
    solicitacao_id = db.Column(db.Integer, db.ForeignKey("solicitacoes.id"), unique=True, nullable=False)
    referencia_recibo = db.Column(db.String(100), nullable=False)
    data_confirmacao = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    responsavel = db.Column(db.String(120), nullable=False)
    origem_confirmacao = db.Column(db.String(80), nullable=False, default="recepcao")
    observacao = db.Column(db.Text, nullable=True)

    solicitacao = db.relationship("Solicitacao", back_populates="confirmacao_pagamento")


class ValidacaoPagamentoFinanceiro(db.Model):
    __tablename__ = "validacoes_pagamento_financeiro"

    id = db.Column(db.Integer, primary_key=True)
    solicitacao_id = db.Column(
        db.Integer,
        db.ForeignKey("solicitacoes.id"),
        unique=True,
        nullable=False,
    )
    referencia_financeira = db.Column(db.String(100), nullable=False)
    responsavel_financeiro = db.Column(db.String(120), nullable=False)
    data_confirmacao = db.Column(db.DateTime, nullable=False)
    registrada_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    registrada_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    solicitacao = db.relationship("Solicitacao", back_populates="validacao_pagamento")
    registrada_por = db.relationship("Usuario")


class Agendamento(db.Model):
    __tablename__ = "agendamentos"

    id = db.Column(db.Integer, primary_key=True)
    solicitacao_id = db.Column(db.Integer, db.ForeignKey("solicitacoes.id"), unique=True, nullable=False)
    paciente_id = db.Column(db.Integer, db.ForeignKey("pacientes.id"), nullable=False)
    medico_id = db.Column(db.Integer, db.ForeignKey("medicos.id"), nullable=False)
    sala_id = db.Column(db.Integer, db.ForeignKey("salas.id"), nullable=False)
    data_hora = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="agendado")
    prioridade = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    solicitacao = db.relationship("Solicitacao", back_populates="agendamento")
    paciente = db.relationship("Paciente", back_populates="agendamentos")
    medico = db.relationship("Medico", back_populates="agendamentos")
    sala = db.relationship("Sala", back_populates="agendamentos")
    historico_status = db.relationship("HistoricoStatus", back_populates="agendamento")
    senha_vinculo = db.relationship("AgendamentoSenha", back_populates="agendamento", uselist=False)


class DisponibilidadeMedica(db.Model):
    __tablename__ = "disponibilidade_medica"

    id = db.Column(db.Integer, primary_key=True)
    medico_id = db.Column(db.Integer, db.ForeignKey("medicos.id"), nullable=False)
    dia_semana = db.Column(db.Integer, nullable=False)
    hora_inicio = db.Column(db.String(8), nullable=False)
    hora_fim = db.Column(db.String(8), nullable=False)
    observacao = db.Column(db.String(200), nullable=True)
    ativo = db.Column(db.Boolean, nullable=False, default=True)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    medico = db.relationship("Medico", back_populates="disponibilidades")
    confirmacoes_presenca = db.relationship(
        "ConfirmacaoPresencaMedica",
        back_populates="disponibilidade",
    )

    __table_args__ = (
        CheckConstraint("dia_semana BETWEEN 0 AND 6", name="check_dia_semana"),
    )


class AusenciaMedica(db.Model):
    __tablename__ = "ausencias_medicas"

    id = db.Column(db.Integer, primary_key=True)
    medico_id = db.Column(db.Integer, db.ForeignKey("medicos.id"), nullable=False)
    inicio = db.Column(db.DateTime, nullable=False)
    fim = db.Column(db.DateTime, nullable=False)
    tipo = db.Column(db.String(30), nullable=False)
    observacao = db.Column(db.String(200), nullable=True)
    ativa = db.Column(db.Boolean, nullable=False, default=True)
    registrada_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    criada_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    medico = db.relationship("Medico")
    registrada_por = db.relationship("Usuario")
    justificativa = db.relationship(
        "JustificativaAusenciaMedica",
        back_populates="ausencia",
        uselist=False,
    )

    __table_args__ = (
        CheckConstraint("fim >= inicio", name="check_ausencia_intervalo"),
    )


class ConfirmacaoPresencaMedica(db.Model):
    __tablename__ = "confirmacoes_presenca_medica"

    id = db.Column(db.Integer, primary_key=True)
    medico_id = db.Column(db.Integer, db.ForeignKey("medicos.id"), nullable=False)
    disponibilidade_id = db.Column(
        db.Integer,
        db.ForeignKey("disponibilidade_medica.id"),
        nullable=False,
    )
    data = db.Column(db.Date, nullable=False)
    confirmada_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    medico = db.relationship("Medico")
    disponibilidade = db.relationship(
        "DisponibilidadeMedica",
        back_populates="confirmacoes_presenca",
    )

    __table_args__ = (
        UniqueConstraint(
            "disponibilidade_id",
            "data",
            name="uq_confirmacao_presenca_turno_data",
        ),
    )


class JustificativaAusenciaMedica(db.Model):
    __tablename__ = "justificativas_ausencia_medica"

    id = db.Column(db.Integer, primary_key=True)
    ausencia_id = db.Column(
        db.Integer,
        db.ForeignKey("ausencias_medicas.id"),
        unique=True,
        nullable=False,
    )
    categoria = db.Column(db.String(20), nullable=False)
    motivo = db.Column(db.Text, nullable=False)
    atestado_conteudo = db.Column(db.LargeBinary, nullable=True)
    atestado_extensao = db.Column(db.String(5), nullable=True)
    registrada_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    criada_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    ausencia = db.relationship("AusenciaMedica", back_populates="justificativa")
    registrada_por = db.relationship("Usuario")


class PoliticaPrioridade(db.Model):
    __tablename__ = "politica_prioridade"

    id = db.Column(db.Integer, primary_key=True)
    aprovada = db.Column(db.Boolean, nullable=False, default=False)
    categorias_habilitadas = db.Column(db.JSON, nullable=False, default=list)
    referencia_aprovacao = db.Column(db.String(100), nullable=True)
    aprovada_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    aprovada_em = db.Column(db.DateTime, nullable=True)
    atualizada_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    aprovada_por = db.relationship("Usuario")


class PrioridadeAgendamento(db.Model):
    __tablename__ = "prioridades_agendamento"

    id = db.Column(db.Integer, primary_key=True)
    agendamento_id = db.Column(
        db.Integer,
        db.ForeignKey("agendamentos.id"),
        unique=True,
        nullable=False,
    )
    categoria = db.Column(db.String(40), nullable=False)
    comprovacao_conferida = db.Column(db.Boolean, nullable=False)
    data_doacao = db.Column(db.Date, nullable=True)
    registrada_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    registrada_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    agendamento = db.relationship("Agendamento")
    registrada_por = db.relationship("Usuario")


class Senha(db.Model):
    __tablename__ = "senhas"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(30), unique=True, nullable=False)
    tipo = db.Column(db.String(20), nullable=False, default="normal")
    paciente_id = db.Column(db.Integer, db.ForeignKey("pacientes.id"), nullable=False)
    medico_id = db.Column(db.Integer, db.ForeignKey("medicos.id"), nullable=True)
    sala_id = db.Column(db.Integer, db.ForeignKey("salas.id"), nullable=True)
    status = db.Column(db.String(30), nullable=False, default="aguardando")
    prioridade = db.Column(db.Boolean, nullable=False, default=False)
    data_hora = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    numero_ordem = db.Column(db.Integer, nullable=False)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    paciente = db.relationship("Paciente", back_populates="senhas")
    medico = db.relationship("Medico", back_populates="senhas")
    sala = db.relationship("Sala", back_populates="senhas")
    historico_chamadas = db.relationship("HistoricoChamada", back_populates="senha")
    vinculo_agendamento = db.relationship("AgendamentoSenha", back_populates="senha", uselist=False)

    @property
    def codigo_exibicao(self):
        prefixo = "P" if self.prioridade else "N"
        return f"{prefixo}-{self.numero_ordem:03d}"


class AgendamentoSenha(db.Model):
    __tablename__ = "agendamento_senhas"

    id = db.Column(db.Integer, primary_key=True)
    agendamento_id = db.Column(
        db.Integer,
        db.ForeignKey("agendamentos.id"),
        unique=True,
        nullable=False,
    )
    senha_id = db.Column(db.Integer, db.ForeignKey("senhas.id"), unique=True, nullable=False)

    agendamento = db.relationship("Agendamento", back_populates="senha_vinculo")
    senha = db.relationship("Senha", back_populates="vinculo_agendamento")


class HistoricoChamada(db.Model):
    __tablename__ = "historico_chamadas"

    id = db.Column(db.Integer, primary_key=True)
    senha_id = db.Column(db.Integer, db.ForeignKey("senhas.id"), nullable=False)
    paciente_id = db.Column(db.Integer, db.ForeignKey("pacientes.id"), nullable=False)
    medico_id = db.Column(db.Integer, db.ForeignKey("medicos.id"), nullable=False)
    sala_id = db.Column(db.Integer, db.ForeignKey("salas.id"), nullable=False)
    status = db.Column(db.String(30), nullable=False)
    data_hora = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    observacao = db.Column(db.Text, nullable=True)

    senha = db.relationship("Senha", back_populates="historico_chamadas")


class Atendimento(db.Model):
    __tablename__ = "atendimentos"

    id = db.Column(db.Integer, primary_key=True)
    paciente_id = db.Column(db.Integer, db.ForeignKey("pacientes.id"), nullable=False)
    medico_id = db.Column(db.Integer, db.ForeignKey("medicos.id"), nullable=False)
    sala_id = db.Column(db.Integer, db.ForeignKey("salas.id"), nullable=False)
    senha_id = db.Column(db.Integer, db.ForeignKey("senhas.id"), nullable=True)
    status = db.Column(db.String(30), nullable=False, default="em_andamento")
    data_inicio = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    data_fim = db.Column(db.DateTime, nullable=True)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    paciente = db.relationship("Paciente", back_populates="atendimentos")
    medico = db.relationship("Medico", back_populates="atendimentos")
    sala = db.relationship("Sala", back_populates="atendimentos")
    senha = db.relationship("Senha")
    prontuario = db.relationship("Prontuario", back_populates="atendimento", uselist=False)
    receitas = db.relationship("Receita", back_populates="atendimento")
    exames = db.relationship("Exame", back_populates="atendimento")


class Prontuario(db.Model):
    __tablename__ = "prontuarios"

    id = db.Column(db.Integer, primary_key=True)
    atendimento_id = db.Column(db.Integer, db.ForeignKey("atendimentos.id"), unique=True, nullable=False)
    queixa_principal = db.Column(db.Text, nullable=False)
    sintomas = db.Column(db.Text, nullable=True)
    historico = db.Column(db.Text, nullable=True)
    observacoes = db.Column(db.Text, nullable=True)
    diagnostico = db.Column(db.Text, nullable=False)
    prescricao = db.Column(db.Text, nullable=True)
    exames_solicitados = db.Column(db.Text, nullable=True)
    condutas = db.Column(db.Text, nullable=True)
    orientacoes = db.Column(db.Text, nullable=True)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    atendimento = db.relationship("Atendimento", back_populates="prontuario")
    receitas = db.relationship("Receita", back_populates="prontuario")
    exames = db.relationship("Exame", back_populates="prontuario")


class Receita(db.Model):
    __tablename__ = "receitas"

    id = db.Column(db.Integer, primary_key=True)
    atendimento_id = db.Column(db.Integer, db.ForeignKey("atendimentos.id"), nullable=False)
    prontuario_id = db.Column(db.Integer, db.ForeignKey("prontuarios.id"), nullable=False)
    medicacoes = db.Column(db.Text, nullable=False)
    orientacoes = db.Column(db.Text, nullable=True)
    validade = db.Column(db.Date, nullable=True)
    criada_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    atendimento = db.relationship("Atendimento", back_populates="receitas")
    prontuario = db.relationship("Prontuario", back_populates="receitas")


class Exame(db.Model):
    __tablename__ = "exames"

    id = db.Column(db.Integer, primary_key=True)
    atendimento_id = db.Column(db.Integer, db.ForeignKey("atendimentos.id"), nullable=False)
    prontuario_id = db.Column(db.Integer, db.ForeignKey("prontuarios.id"), nullable=False)
    nome = db.Column(db.String(150), nullable=False)
    descricao = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), nullable=False, default="solicitado")
    solicitado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    atendimento = db.relationship("Atendimento", back_populates="exames")
    prontuario = db.relationship("Prontuario", back_populates="exames")


class RegistroAuditoria(db.Model):
    __tablename__ = "registros_auditoria"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    entidade = db.Column(db.String(100), nullable=False)
    entidade_id = db.Column(db.Integer, nullable=False)
    acao = db.Column(db.String(80), nullable=False)
    detalhe = db.Column(db.Text, nullable=True)
    ip = db.Column(db.String(40), nullable=True)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    usuario = db.relationship("Usuario", back_populates="registros_auditoria")


class HistoricoStatus(db.Model):
    __tablename__ = "historico_status"

    id = db.Column(db.Integer, primary_key=True)
    entidade = db.Column(db.String(100), nullable=False)
    entidade_id = db.Column(db.Integer, nullable=False)
    status_anterior = db.Column(db.String(60), nullable=True)
    status_novo = db.Column(db.String(60), nullable=False)
    alterado_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    solicitacao_id = db.Column(db.Integer, db.ForeignKey("solicitacoes.id"), nullable=True)
    agendamento_id = db.Column(db.Integer, db.ForeignKey("agendamentos.id"), nullable=True)
    criado_em = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    usuario = db.relationship("Usuario", back_populates="historico_status")
    solicitacao = db.relationship("Solicitacao", back_populates="historico_status")
    agendamento = db.relationship("Agendamento", back_populates="historico_status")
