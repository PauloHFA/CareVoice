# CareVoice AI

Base de implementação para uma ferramenta de apoio à documentação clínica. O sistema deverá
organizar relatos de profissionais, exigir revisão e aprovação antes de registrar uma evolução
como final e não deverá diagnosticar nem recomendar condutas.

## Estado atual

Implementados até agora: fundação Python, configuração tipada, logging com redação de campos
sensíveis, banco SQLAlchemy, proteção criptográfica de campos pessoais, convites de uso único,
revogação de profissionais, isolamento por profissional, cadastros básicos, consentimento, metas,
validação de arquivos de áudio e fila persistente com payload criptografado, retries limitados e
checagem de consentimento antes do processamento. Há um adaptador local para faster-whisper,
schemas estritos para SOAP/ABC/livre, resolução conservadora de homônimos e verificação de
evidências e medidas contra a transcrição. A verificação atual valida presença textual e números,
mas não prova equivalência semântica; exige-se revisão profissional. O faster-whisper ainda não foi
avaliado com conjunto representativo de áudios. Ainda faltam o bot/worker, geração de rascunhos
com LLM, revisão/aprovação e documentos. Não use esta versão com dados de pacientes.

## Desenvolvimento local

Requer Python 3.11 ou superior.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
alembic upgrade head
pytest
ruff check .
mypy carevoice
```

For local transcription, install the optional model adapter with
`python -m pip install -e ".[audio]"`. Model weights are loaded when transcription begins; keep
the first model download within an approved, controlled environment.

O processamento local e o uso de dados fictícios são os padrões. A habilitação técnica de um
provedor em nuvem não substitui consentimento por paciente, base legal, contratos com operadores,
avaliação de transferência internacional ou revisão jurídica. O Telegram é destinado apenas a
testes com dados fictícios até que o canal seja avaliado para uso real.

## Segurança e privacidade

- Nunca registre áudio, transcrição, conteúdo clínico, nomes ou segredos em logs.
- Nunca coloque credenciais no código, em arquivos versionados ou em mensagens de erro.
- Configure segredos por ambiente seguro; `.env` é local e ignorado pelo Git.
- Os campos de identificação e contato são criptografados na aplicação. Defina
  `CAREVOICE_FIELD_ENCRYPTION_KEY` com uma chave Fernet gerada e armazenada fora do banco; perder
  ou trocar a chave sem um procedimento de rotação torna esses campos irrecuperáveis.
- A configuração inicial do esquema usa Alembic (`alembic upgrade head`). SQLite é apenas para
  desenvolvimento/testes; produção exige PostgreSQL.
- `CAREVOICE_ADMINISTRATOR_CHAT_ID` deve ser configurado para emitir convites. Nunca compartilhe
  convites; são tokens de uso único com validade padrão de 24 horas.
- Dados reais permanecem desabilitados por padrão. A configuração ainda não constitui um fluxo
  funcional de autorização ou consentimento.
- Antes de qualquer uso real, concluir RIPD, modelagem de ameaças, revisão jurídica, política de
  retenção e avaliação do canal e dos provedores.

## Qualidade

O CI executa Ruff, mypy, testes com limite de cobertura do núcleo e auditoria de dependências.
Os critérios clínicos de WER e fidelidade exigem conjuntos de avaliação apropriados; não são
validados por estes testes de fundação.
