# Clínica Nexo

Sistema web para gestão de clínica particular, com foco em recepção, atendimento médico, administração e painel público.

## Requisitos

- Python 3.11+
- pip
- SQLite

## Checklist para execução local (Windows e VS Code)

- [ ] Abra a pasta do projeto no VS Code e use o terminal PowerShell integrado.
- [ ] Confirme que o Python instalado é 3.11 ou superior:

  ```powershell
  py --version
  ```

- [ ] Crie e ative o ambiente virtual, e instale as dependências:

  ```powershell
  py -m venv .venv
  .\.venv\Scripts\Activate.ps1
  python -m pip install -r requirements.txt
  ```

- [ ] No VS Code, selecione o interpretador Python dentro de `.venv` usando **Python: Select Interpreter**.
- [ ] Inicie a aplicação no terminal:

  ```powershell
  python app.py
  ```

- [ ] Abra http://127.0.0.1:5000 e confirme que `/health` e `/ready` respondem.
- [ ] Para um banco de desenvolvimento recém-criado, o primeiro acesso administrativo é `admin` / `Admin@123`. A senha só é definida na criação inicial; uma conta existente não é redefinida automaticamente.
- [ ] Rode a suíte de testes quando validar mudanças:

  ```powershell
  $env:DATABASE_URL = "sqlite://"
  python -m unittest discover -s tests -v
  Remove-Item Env:DATABASE_URL
  ```

- [ ] Se precisar criar uma cópia local do banco, execute `python backup_database.py backup`. Os arquivos de backup não são criptografados; não use dados reais de pacientes neste ambiente sem autorização e controles adequados.
- [ ] Ao terminar, pare o servidor com **Ctrl+C** no terminal.

A execução local usa `127.0.0.1` e o banco SQLite em `instance/clinica_nexo.db`. Nenhum servidor de produção, domínio, hospedagem ou tarefa agendada é configurado por este checklist.

## Estrutura inicial

- `app.py`: aplicação Flask principal
- `config.py`: configurações gerais
- `templates/`: páginas visuais
- `static/`: estilos, scripts e recursos estáticos
- `instance/`: banco SQLite local

## Perfis e permissões

O servidor valida perfil e permissão em cada rota; a interface também oculta as ações incompatíveis:

- **Administrador:** usuários e permissões, médicos, especialidades, salas (incluindo o médico responsável por cada sala), catálogo de serviços e preços, configuração da política de prioridade, relatórios agregados e auditoria. Não acessa cadastros nem dados identificáveis de pacientes, atendimentos/pagamentos, solicitações, agenda operacional ou filas de pacientes.
- **Recepção:** cadastro de pacientes sem exigir e-mail e registro do serviço solicitado na mesma página, com dados do paciente e atendimento lado a lado. Ao cadastrar, seleciona um médico responsável da especialidade; esse nome aparece em **Atendimentos e pagamentos** e no caixa. O catálogo não fica acessível como página; o valor aparece após selecionar o serviço. Emite um documento de encaminhamento ao financeiro (não é recibo de pagamento) e acompanha solicitações. Pode agendar atendimentos futuros e acompanhar/imprimir senhas já emitidas, mas não emite senhas. Ao agendar, vê médicos ativos da especialidade e sem conflito no horário escolhido, sem depender de confirmação de presença; a sala atribuída pelo administrador é aplicada automaticamente. Não valida pagamentos. Não pode alterar salas, preços, administrar usuários, chamar pacientes ou acessar registros clínicos.
- **Médico:** requer conta vinculada a um cadastro médico. Ao entrar no sistema, sua presença é ativada automaticamente e permanece ativa até sair; agenda e fila são filtradas para esse cadastro. Só chama a próxima senha da própria fila enquanto sua presença estiver ativa. Ao chamar, inicia um atendimento em andamento e pode preencher o prontuário com queixa principal, sintomas, diagnóstico, prescrição, exames, condutas e orientações. Salvar finaliza o atendimento e libera a próxima senha; registros finalizados não podem ser editados. O histórico e a impressão do prontuário ficam restritos a médicos com `gerenciar_atendimento`. Não acessa o catálogo de serviços ou dados cadastrais de pacientes.
- **Financeiro:** consulta solicitações pendentes, registra pagamentos reais por Pix, dinheiro, cartão ou convênio, com referência/observação opcionais. A validação oficial é registrada com a conta responsável e libera a solicitação; havendo médico ativo da especialidade e horário disponível no dia, o sistema agenda o próximo horário de 30 minutos e emite automaticamente uma senha para a fila. Também emite pelo caixa as senhas dos agendamentos futuros quando chegam ao dia marcado. O código e o botão de impressão aparecem no caixa. Se não houver disponibilidade imediata, a solicitação permanece confirmada para agendamento posterior. Não administra pacientes, agenda operacional, fila ou usuários.

Ao editar um usuário legado, as permissões são limitadas ao perfil selecionado e as permissões antigas equivalentes são convertidas para os novos acessos específicos. Revise as permissões dos usuários existentes após a atualização; não são removidas contas nem apagados registros clínicos históricos.

Nas listas de médicos, salas, especialidades, serviços, usuários e pacientes, a ação **Excluir** remove permanentemente apenas cadastros sem registros vinculados. Quando há histórico ou dependências, a exclusão é recusada; use **Inativar/Desativar** para manter os dados. Excluir um cadastro de médico não exclui a conta de usuário associada, que permanece na lista de usuários.

## Agenda médica

A recepção pode criar/cancelar agendamentos e consultar a agenda operacional; o médico vê somente a própria agenda. Após validar um pagamento, o financeiro também pode gerar automaticamente um agendamento imediato e senha quando houver médico ativo da especialidade e horário livre no dia. O administrador cadastra primeiro o médico, depois registra cada sala em **Salas** e seleciona seu médico responsável. Uma sala e um médico só podem ter um vínculo responsável por vez. Não há escala semanal de dias e horários nem registro de férias, faltas ou justificativas. No agendamento, a recepção seleciona solicitação e data/hora; o sistema lista médicos ativos da especialidade, sem conflito, independentemente de estarem conectados, e usa automaticamente a sala atribuída. Salas inativas ou marcadas como indisponíveis são bloqueadas; o estado atual “ocupada” não impede, por si só, um horário futuro sem conflito. No dia do agendamento futuro, o financeiro emite a senha pelo caixa; a recepção não confirma a chegada nem emite senhas. A validação dessas regras também ocorre no servidor.

Somente solicitações com validação financeira registrada podem ser agendadas. O sistema valida especialidade, conta médica ativa, sala ativa e conflitos de agenda; a presença é exigida para chamar pacientes, não para agendar ou selecionar o médico. Os horários usam blocos fixos de 30 minutos, iniciados na hora cheia ou na meia hora. Um agendamento só pode ser cancelado enquanto ativo e antes da emissão de senha.

## Pagamentos

O perfil financeiro confirma no sistema o pagamento efetivamente recebido, identifica o médico responsável selecionado pela recepção e registra forma, referência/observação opcional, usuário responsável e data/hora da confirmação em `ValidacaoPagamentoFinanceiro`; os dados complementares ficam em `ConfirmacaoPagamento`. Quando há disponibilidade, o agendamento e a senha são vinculados ao médico selecionado. O status e a trilha de histórico/auditoria são atualizados na mesma operação. A recepção não valida pagamentos; o documento impresso serve apenas para identificar a solicitação no caixa. Nenhuma integração com gateway bancário é criada.

Registros antigos de recibo são preservados, mas não autorizam novos agendamentos sem uma validação oficial em `ValidacaoPagamentoFinanceiro`. Os relatórios calculam valores recebidos pela data dessa validação.

## Massa de demonstração

Para apagar os dados operacionais do banco SQLite configurado e gerar registros fictícios, execute `python seed_demo.py --confirm-clear`. O script preserva o administrador e as permissões e recusa execução com `APP_ENV=production`; não use a senha padrão `123456` fora de um ambiente local de demonstração.

## Fluxo simplificado da recepção

No dashboard da recepção, selecione **Novo atendimento**. Em uma única página, escolha um paciente já cadastrado ou preencha os dados de um novo paciente (sem campo de e-mail), selecione o serviço e o médico responsável da especialidade. O valor aparece após a seleção do serviço para que seja informado ao paciente. O cadastro do paciente e a solicitação são salvos juntos, com o valor vigente e o médico escolhido registrados na solicitação. O sistema abre o documento de encaminhamento para impressão; ele informa serviço e valor, mas não confirma pagamento. O catálogo completo permanece acessível somente ao administrador.

Após o pagamento real, o operador do financeiro confirma o pagamento no sistema. Havendo médico ativo da especialidade e horário livre no dia, o sistema agenda automaticamente o próximo bloco de 30 minutos, emite a senha e a vincula à fila do médico. O código aparece em **Senhas emitidas** no caixa, onde pode ser impresso. Se não houver horário disponível no dia, a recepção pode agendar para outra data; no dia do atendimento, somente o financeiro emite a senha pelo caixa. A recepção pode acompanhar e imprimir senhas já emitidas, mas não pode emiti-las. O médico poderá chamar pacientes quando estiver conectado. O bilhete impresso contém código curto e sala, sem nome do médico ou horário.

## Fila de atendimento

Na tela **Fila**, a recepção acompanha todas as filas, imprime bilhetes já emitidos e registra não comparecimento. O financeiro emite, pelo caixa, senhas para os agendamentos do dia que ainda não as possuem; para atendimento do mesmo dia, a senha é criada automaticamente após a confirmação financeira quando houver disponibilidade. A nova senha é vinculada ao médico responsável e uma atualização Socket.IO é emitida após a transação ser salva. A senha aguardando não aparece como chamada no painel público; somente o médico da fila, enquanto estiver conectado, pode chamar a próxima senha. O painel público consulta as chamadas aproximadamente a cada segundo. Uma chamada/consulta ativa impede chamar outra até ser encerrada. O administrador não pode acessar a fila de pacientes, e a fila é separada por médico.

As categorias prioritárias começam desativadas. Um administrador pode habilitá-las apenas após a aprovação formal da direção/responsável técnico, registrando quem aprovou, quando e a referência da aprovação. Ao emitir senha no caixa, o financeiro registra somente a categoria, a confirmação administrativa de comprovação e, para doador de sangue, a data da doação; não são armazenados documentos nem diagnósticos. Comprovantes de doação com mais de 120 dias são recusados. A ordem é: demais categorias prioritárias, doadores de sangue e, em seguida, atendimento normal. Prioridade não muda o médico/especialidade do agendamento. Urgências clínicas devem ser avaliadas por profissional de saúde, fora da decisão administrativa.

O bilhete impresso não contém nome nem diagnóstico do paciente.

O painel público fica disponível em `/painel`, sem login, e consulta novas chamadas aproximadamente a cada segundo. Ele exibe o nome do paciente, o código da senha, a sala e o horário da chamada (com segundos), sem nome do médico; a chamada mais recente é anunciada em português brasileiro pelo nome do paciente e pela sala. A voz pode ser silenciada no próprio painel.

## Segurança operacional

Todos os formulários de alteração usam proteção CSRF; logout também é uma operação POST. Redirecionamentos após login são limitados a caminhos locais. As respostas incluem cabeçalhos básicos de proteção e desabilitam cache. O login não mantém um cookie persistente de “lembrar-me”, e a rota de diagnóstico de permissões não é publicada.

A visualização e as alterações de pacientes, solicitações, agenda, fila e prontuários registram usuário, ação, entidade, horário e IP observado pelo servidor em `registros_auditoria`. O log não copia CPF, dados pessoais ou conteúdo clínico. Dados e atestados de ausências registrados antes da remoção do recurso permanecem nas tabelas antigas e nos backups, mas não podem ser consultados nem alterados pela aplicação; proteja os backups com criptografia e acesso restrito. Registros clínicos históricos permanecem preservados no banco. Defina controles de acesso e prazo de retenção para esses registros junto à política da clínica. Essas medidas técnicas não substituem uma avaliação jurídica ou um programa completo de conformidade com a LGPD.

Usuários com a permissão `consultar_auditoria` podem revisar os eventos em **Auditoria**, com filtro de período e paginação. A tela omite detalhes e conteúdo clínico; apenas administradores recebem essa permissão automaticamente.

## Implantação em produção

Use um gerenciador de segredos para fornecer `APP_ENV=production`, `SECRET_KEY` e `ADMIN_INITIAL_PASSWORD` ao processo. Gere um segredo aleatório (por exemplo, `python -c "import secrets; print(secrets.token_hex(32))"`) e não o armazene no código ou no controle de versão. `ADMIN_INITIAL_PASSWORD` só é usada quando a conta `admin` ainda não existe; configurar essa variável não troca a senha de uma conta já criada.

Por padrão, o banco continua em `instance/clinica_nexo.db`, preservando a localização usada no desenvolvimento. Se necessário, `DATABASE_URL` permite configurar outra URL SQLAlchemy. Garanta que o serviço tenha permissão de escrita no diretório do banco e mantenha cópias de segurança criptografadas, fora do servidor, com restaurações testadas. Para SQLite, faça o backup com o serviço parado ou usando uma ferramenta compatível com SQLite.

Instale as dependências e inicie com Waitress, mantendo o servidor ligado apenas à interface local atrás de um proxy reverso que forneça HTTPS:

```powershell
pip install -r requirements.txt
$env:APP_ENV = "production"
$env:SECRET_KEY = "<segredo fornecido pelo gerenciador de segredos>"
$env:ADMIN_INITIAL_PASSWORD = "<senha inicial fornecida pelo gerenciador de segredos>"
waitress-serve --listen=127.0.0.1:8000 app:app
```

O HTTPS deve ser terminado no proxy reverso; não exponha o servidor de desenvolvimento nem a porta do Waitress diretamente à internet. Use um supervisor para reiniciar o processo e encaminhar/rotacionar seus logs. `HOST` e `PORT` configuram a execução por `python app.py`; ao iniciar pelo comando `waitress-serve`, configure endereço e porta com `--listen`.

`/health` verifica se o processo está respondendo e `/ready` verifica também o acesso ao banco de dados. A aplicação cria as tabelas ausentes e aplica migrações aditivas para `medicos.sala_id`, `medicos.presenca_ativa` e `politica_prioridade.referencia_aprovacao`, sem substituir tabelas nem apagar registros; médicos antigos ficam sem sala atribuída até que o administrador a escolha, e a presença começa desativada até o próximo login do médico. O índice único de `medicos.sala_id` garante uma sala exclusiva por médico. As tabelas legadas de escala, ausências e justificativas são preservadas e deixaram de controlar a operação; não são apagadas nem disponibilizadas na aplicação. Também são criadas as tabelas `politica_prioridade`, `prioridades_agendamento` e `validacoes_pagamento_financeiro` quando ainda não existem. Agendamentos e demais registros existentes são preservados. Antes de atualizar o código em outros ambientes, pare o sistema e faça backup com `python backup_database.py backup`; valide a cópia e mantenha-a protegida.

## Backup e recuperação

Crie uma cópia consistente do SQLite a qualquer momento com a API de backup do próprio SQLite (inclui alterações confirmadas em WAL):

```powershell
python backup_database.py backup
```

Por padrão, os arquivos ficam em `instance/backups`; `BACKUP_DIR` pode apontar para outro destino. Também é possível informar `--output <caminho>`. Backups podem conter prontuários históricos e outros dados pessoais: restrinja o acesso ao diretório, mantenha cópias criptografadas fora do servidor e não as envie para serviços sem aprovação da clínica. A ferramenta não criptografa os arquivos.

Para criar o backup e remover cópias gerenciadas com mais de 30 dias:

```powershell
python backup_database.py backup --retain-days 30
```

A retenção aplica-se somente aos arquivos `clinica-nexo-*.db` e `pre-restore-*.db` diretamente dentro de `BACKUP_DIR`; outros arquivos e subpastas não são removidos. No Windows, configure o **Agendador de Tarefas** para executar diariamente às 02:00: use o `python.exe` do ambiente virtual como programa, `backup_database.py backup --retain-days 30` como argumentos e a pasta do projeto como diretório inicial. Configure `DATABASE_URL` e `BACKUP_DIR` no ambiente da conta da tarefa e monitore o histórico de execução. Na implantação em outro sistema operacional, configure o agendador equivalente no servidor.

Para recuperar, pare o serviço da aplicação e execute o comando abaixo apontando para um backup confiável. A opção `--confirm` é obrigatória; antes da substituição, a ferramenta cria uma cópia de segurança automática do banco atual no diretório de backups:

```powershell
python backup_database.py restore "C:\caminho\para\backup.db" --confirm
```

Após a restauração, inicie o serviço e confirme `/ready` e os fluxos essenciais. Faça exercícios periódicos de restauração em uma cópia isolada, nunca no banco em uso. Agende backups regulares por um supervisor do sistema operacional e monitore falhas e espaço disponível.

## Atendimento médico

Após chamar uma senha, o médico responsável seleciona **Fazer prontuário** na fila, preenche o formulário e salva; o sistema então finaliza o atendimento e atualiza senha, agendamento e solicitação. A opção **Prontuário** no menu do médico abre a lista dos atendimentos sob sua responsabilidade. Senhas já concluídas sem registro clínico podem receber documentação posterior pelo mesmo botão, sem reabrir nem alterar o status da fila; essa inclusão fica auditada. Queixa principal e diagnóstico são obrigatórios; sintomas, prescrição, exames solicitados, condutas e orientações são opcionais. Prontuários salvos são somente leitura e podem ser consultados e impressos pelo médico responsável. Durante um atendimento, o médico também pode consultar e imprimir prontuários anteriores do mesmo paciente. As rotas de conteúdo clínico exigem login, perfil médico e permissão `gerenciar_atendimento`; recepção, financeiro e administrador não podem acessá-las. Nenhuma coluna ou tabela existente é alterada.

## Relatórios e Indicadores

A tela **Relatórios** permite consultar dados reais por período diário, mensal, anual ou personalizado e filtrar por médico ou consolidar todos. Apresenta agendamentos, atendimentos concluídos, cancelamentos, faltas, pacientes distintos atendidos, produtividade por médico, horários de maior movimento, valores recebidos/pedentes e faturamento confirmado no dia. Valores recebidos usam a data de validação oficial do financeiro; pendências usam solicitações sem validação no período. Gráficos, tabelas e exportação CSV usam os mesmos filtros, sem exibir identificação de pacientes. O acesso requer `consultar_relatorios`.
