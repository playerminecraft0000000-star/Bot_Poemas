import os
import re
import time
import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

# VARIÁVEIS LOCAIS
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not all([EMAIL_USER, EMAIL_PASS, ADMIN_EMAIL, GEMINI_API_KEY]):
    raise ValueError("Variáveis de ambiente faltando!")

genai.configure(api_key=GEMINI_API_KEY)

# DADOS GLOBAL
poemas = []
usuarios_estado = {}
usuarios_poema = {}


# GERAR 30 POEMAS NO INÍCIO
def gerar_poemas_na_inicializacao():
    global poemas
    print("Gerando poemas...")

    prompt = """
    Gere exatamente 30 poemas curtos, cada um deve ter um titulo e um autor brasileiro diferente.

    Regras obrigatórias:
    1. Cada poema deve ser de um autor brasileiro diferente. Nenhum autor pode se repetir.
    2. Cada poema deve ter no mínimo 6 linhas e no máximo 15 versos.
    3. Cada poema deve ter um título na primeira linha.
    4. O nome do autor deve aparecer na última linha, precedido por uma linha em branco.
    5. Os poemas devem transmitir sentimentos de força, encorajamento, animação e disposição.
    6. Você pode usar autores clássicos ou contemporâneos, desde que todos sejam brasileiros.
    7. O formato de saída deve ser: Número do poema (seguido por ponto e espaço), Título, Versos, Linha em branco, Autor. Exemplo:

       1. Título do Poema
          Verso 1
          Verso 2

          Autor: Nome do Autor

    Não escreva nada além dos 30 poemas nesse formato.
    """

    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        resposta = model.generate_content(prompt).text
        blocos = re.split(r'\n\n (?=\d{1,2}\.\s)', resposta)
        poemas = [b.strip() for b in blocos if b.strip()]
        if len(poemas) != 30:
            raise ValueError(f"Quantidade incorreta de poemas: {len(poemas)} encontrados, 30 esperados.")
        print("Poemas gerados com sucesso.")
    except Exception as e:
        print(f"Erro crítico na Geração de Poemas: {e}")


# ENVIAR E-MAIL
def enviar_email(destino, assunto, corpo):
    msg = MIMEText(corpo, "plain", "utf-8")
    msg["From"] = EMAIL_USER
    msg["To"] = destino
    msg["Subject"] = assunto

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(EMAIL_USER, EMAIL_PASS)
            smtp.send_message(msg)
        print("E-mail enviado para", destino)
    except Exception as e:
        print(f"Erro ao enviar e-mail para {destino}: {e}")


# MARCAR E-MAIL COMO LIDO
def marcar_email_como_lido(email_id):
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select("inbox")
        mail.store(email_id, '+FLAGS', '\\Seen')
        mail.logout()
    except Exception as e:
        print(f"Erro ao marcar e-mail {email_id} como lido: {e}")


# LER NOVOS E-MAILS (Retorna o ID do e-mail)
def ler_novos_emails():
    mensagens = []
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select("inbox")

        status, data = mail.search(None, "UNSEEN")
        emails_novos = data[0].split()

        for num in emails_novos:
            status, dados = mail.fetch(num, "(RFC822)")
            raw = email.message_from_bytes(dados[0][1])

            remetente = email.utils.parseaddr(raw["From"])[1]

            corpo = ""
            if raw.is_multipart():
                for part in raw.walk():
                    # Ignora HTML e anexo, foca em texto puro
                    if part.get_content_type() == "text/plain":
                        try:
                            corpo = part.get_payload(decode=True).decode()
                            break
                        except UnicodeDecodeError:
                            corpo = part.get_payload(decode=True).decode('latin-1')
                            break
            else:
                corpo = raw.get_payload(decode=True).decode()

            mensagens.append((remetente, corpo.strip(), num))

        mail.logout()
    except Exception as e:
        print(f"Erro ao conectar/ler e-mails: {e}")

    return mensagens


# FILTRAR LISTA DE E-MAILS
def filtrar_emails(texto):
    return re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", texto)


# HELPER: Gera a lista de poemas formatada (para o Admin)
def get_lista_poemas():
    lista = "<=SELEÇÃO SEMANAL DE POEMAS=>\nVovô, escolha um poema digitando o número dele:\n\n"

    for i, p in enumerate(poemas):
        primeira_linha = p.split('\n', 1)[0]
        titulo = re.sub(r'^\d+\.\s*', '', primeira_linha).strip()
        corpo_poema = p.split('\n', 1)[-1]

        # Adiciona o número de seleção + o corpo do poema (sem o título)
        lista += f"{i + 1}. {titulo} \n{corpo_poema}\n\n"
    return lista


# LOOP PRINCIPAL
def processar_emails():
    msgs = ler_novos_emails()

    for remetente, texto, num_id in msgs:

        # Ação final para garantir que o e-mail não seja lido novamente
        marcar_email_como_lido(num_id)

        # 1. Apenas admin pode usar
        if remetente != ADMIN_EMAIL:
            enviar_email(remetente, "Acesso negado", "Apenas o administrador (WILFREDO VOVÔ) pode usar esse bot.")
            continue  # Próximo e-mail

        # 2. ADMIN pediu "poemas" (gatilho manual)
        if texto.lower() == "poemas":
            if not poemas:
                enviar_email(ADMIN_EMAIL, "Erro", "A lista de poemas não foi carregada.")
                continue

            enviar_email(ADMIN_EMAIL, "Lista de Poemas", get_lista_poemas())
            usuarios_estado[ADMIN_EMAIL] = "escolhendo"
            continue  # Próximo e-mail

        # 3. ADMIN escolhe poema
        if usuarios_estado.get(ADMIN_EMAIL) == "escolhendo":

            try:
                resposta_limpa = texto.split()[0].strip()
            except IndexError:
                # Se o e-mail for totalmente vazio ou só com espaços
                resposta_limpa = ""

                # Repete o prompt em caso de número inválido
            # Agora usa resposta_limpa
            if not resposta_limpa.isdigit() or not (1 <= int(resposta_limpa) <= len(poemas)):
                enviar_email(ADMIN_EMAIL, "Número Inválido. Tente Novamente vovô.",
                             f"Por favor, escolha um número de 1 a {len(poemas)}.\n\n" + get_lista_poemas())
                continue  # Próximo e-mail

            # Usa a resposta limpa para selecionar o poema
            poema = poemas[int(resposta_limpa) - 1]
            usuarios_poema[ADMIN_EMAIL] = poema
            usuarios_estado[ADMIN_EMAIL] = "enviando"

            enviar_email(ADMIN_EMAIL, "Envie os E-mails",
                         f"Vovô, o poema {resposta_limpa} foi selecionado, obrigado por selecionar o poema. Agora envie os e-mails dos destinatários separados por vírgula.")
            continue

        # 4. ADMIN envia lista de e-mails
        if usuarios_estado.get(ADMIN_EMAIL) == "enviando":
            contatos = filtrar_emails(texto)

            # Repete o prompt em caso de e-mail(s) inválido(s)
            if not contatos:
                enviar_email(ADMIN_EMAIL, "Erro: Formato Inválido",
                             "Nenhum e-mail válido encontrado. Envie os e-mails no formato padrão (nome@dominio.com), separados por vírgula.")
                continue  # Próximo e-mail

            poema = usuarios_poema[ADMIN_EMAIL]
            for c in contatos:
                enviar_email(c, "Esse poema foi selecionado para você com muito carinho pelo senhor Wilfredo: ", poema[3:])

            enviar_email(ADMIN_EMAIL,
                         "Concluído, (Te amo vovô wilfredo, você é o melhor vovô do mundo) se recebeu a mensagem entre parenteses conta para mim no whatsapp",
                         f"Poema enviado para {len(contatos)} pessoas!")

            usuarios_estado[ADMIN_EMAIL] = None
            usuarios_poema.pop(ADMIN_EMAIL, None)
            continue  # Próximo e-mail


# INICIAR
if __name__ == "__main__":
    gerar_poemas_na_inicializacao()

    # inicia a conversa automaticamente
    if poemas:
        print("Enviando prompt de início para o ADMIN_EMAIL...")

        # 1. Envia o e-mail de início
        enviar_email(ADMIN_EMAIL, "<------ Seleção de Poemas ------>", get_lista_poemas())

        # 2. Define o estado do ADMIN imediatamente para 'escolhendo'
        usuarios_estado[ADMIN_EMAIL] = "escolhendo"
    else:
        print("ERRO: Não foi possível iniciar a conversa. Poemas não gerados.")

    print("Bot iniciado. Lendo e-mails a cada 5 segundos...")
    while True:
        processar_emails()
        time.sleep(5)
