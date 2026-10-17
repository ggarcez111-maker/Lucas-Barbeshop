# Lucas Barbershop — site premium + agendamento independente

Este projeto **não usa a Trinks** e inclui o próprio sistema de agendamento e painel administrativo.

## Rodar no computador (teste)

Precisa de Python 3.10+.

```bash
python -m venv .venv
# Linux/Mac: source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
# Defina ADMIN_PASSWORD e SESSION_SECRET antes de iniciar.
# PowerShell: $env:ADMIN_PASSWORD="sua-senha-longa"; $env:SESSION_SECRET="uma-chave-aleatoria-longa-de-32-caracteres"
# Bash: export ADMIN_PASSWORD="sua-senha-longa" SESSION_SECRET="uma-chave-aleatoria-longa-de-32-caracteres"
uvicorn app:app --reload
```

- Site: http://127.0.0.1:8000/
- Painel: http://127.0.0.1:8000/admin
- O SQLite em `data/agenda.sqlite3` grava as reservas e persiste entre reinicializações locais.

## Publicação online

**Atenção:** abrir o arquivo HTML diretamente ou subir apenas os arquivos estáticos à Vercel não ativa a agenda. Precisa publicar o **servidor Python** e conectar um banco persistente.

Caminho sugerido: hospedar o app Python no **Render/Railway** como web service, com **PostgreSQL persistente**. Coloque este projeto em um repositório GitHub, conecte o repositório ao serviço de hospedagem e configure:

- Comando de instalação: `pip install -r requirements.txt`
- Comando para iniciar: `uvicorn app:app --host 0.0.0.0 --port $PORT`
- `ENVIRONMENT=production`
- `DATABASE_URL=postgresql://...` (obtido no banco PostgreSQL, nunca público)
- `ADMIN_PASSWORD=` senha administrativa segura, com 12 ou mais caracteres
- `SESSION_SECRET=` sequência aleatória de 32 ou mais caracteres, manter em segredo

O servidor se recusa a ligar em modo de produção se faltar qualquer segredo ou PostgreSQL. Use HTTPS. Não coloque credenciais no GitHub.

Se quiser usar Vercel para a página pública, será necessário separar o frontend dos endpoints e apontá-los ao backend. **A versão entregue foi construída para servir página e API no mesmo domínio** e assim evitar configuração problemática e cookies de domínios diferentes.

## Como usar

1. Acesse `/admin` com a senha que você configurou.
2. **Obrigatório antes da abertura ao público:** substitua `Profissional 1 — editar nome` pelo barbeiro correto, cadastre os demais, confira todos os serviços, suas durações, preços reais, horário semanal e dias fechados. Esses dados vêm inicialmente como **exemplos editáveis** e não foram verificados com a barbearia.
3. Teste a marcação com nome e telefone de teste e confirme se aparece no painel.
4. Marque e cancele uma reserva pelo painel: o horário deve aparecer livre novamente após cancelamento.
5. Providencie fotos reais para substituir a imagem ilustrativa do topo.

## Funcionalidades incluídas

- Reserva por serviço, barbeiro, data e hora, sem dependência de plataforma de agendamento.
- Exibição de horários por blocos de 15 minutos, calculados segundo a duração do serviço.
- Bloqueio de horários ocupados, incluindo sobreposição de serviços de durações diferentes; serialização transacional para reservas simultâneas.
- Janela de reserva de até 60 dias, antecedência mínima de 45 minutos e fuso de Brasília.
- Painel privado: agenda do dia, status (confirmado, concluído, cancelado, falta), serviços/preços, profissionais, horários semanais e dias indisponíveis.
- Confirmação na tela e botão de contato por WhatsApp; **não envia mensagens automaticamente**.
- Dados guardados na base da própria aplicação, fora do navegador do cliente.

## Limitações antes de uma operação comercial completa

- Não há pagamento online, disparo automático de WhatsApp/SMS/e-mail, conta de cliente nem cancelamento automático pelo cliente.
- O expediente vale para todos os barbeiros cadastrados: ainda não há escala individual por profissional.
- Mudanças no expediente e bloqueios de dia **não cancelam reservas antigas**. Verifique a agenda e avise o cliente.
- É preciso definir política de privacidade/LGPD (retenção, acesso, exclusão de dados), backups, monitoramento e testes no ambiente público.
- Não há importação/sincronização da agenda antiga: enquanto as reservas existentes na Trinks não forem migradas ou encerradas, será necessário evitar atendimento duplicado.
- Serviço PostgreSQL e hospedagem podem ter custos; a autonomia sobre agendamentos não significa ausência de infraestrutura.

## Organização

- `app.py`: API, regras de agenda e banco de dados
- `static/index.html`: site para clientes
- `static/admin.html`: painel administrativo
- `static/logo-lucas.png`: logo
- `requirements.txt`: dependências Python
