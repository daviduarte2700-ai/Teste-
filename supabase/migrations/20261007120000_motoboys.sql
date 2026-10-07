-- Agente dos motoboys: cadastro, documentos, escala, coberturas, ocorrências e conversas.
-- Projeto: painel-hashtag. As tabelas só são acessadas pelo bot (service role), por isso
-- RLS fica ligado e sem políticas: nada fica exposto pela chave pública.

create table if not exists public.motoboys (
  id            bigint generated always as identity primary key,
  telefone      text not null unique,             -- só dígitos, com 55 (ex.: 5585999998888)
  nome          text,
  cpf           text,
  cidade        text,                             -- mesmo formato de lojas.cidade (ex.: "Fortaleza - CE")
  chave_pix     text,
  tipo_pix      text check (tipo_pix in ('cpf','telefone','email','aleatoria','cnpj')),
  moto_placa    text,
  moto_modelo   text,
  status        text not null default 'pendente'
                check (status in ('pendente','ativo','inativo','bloqueado')),
  observacoes   text,
  criado_em     timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);

create table if not exists public.motoboy_documentos (
  id                bigint generated always as identity primary key,
  motoboy_id        bigint not null references public.motoboys(id) on delete cascade,
  tipo              text not null check (tipo in ('cnh','crlv','comprovante_residencia','foto_rosto','mei','outro')),
  numero            text,
  validade          date,
  nome_no_documento text,
  arquivo           text,                         -- caminho no bucket "motoboys"
  status            text not null default 'pendente_validacao'
                    check (status in ('pendente_validacao','aprovado','recusado')),
  observacao        text,
  criado_em         timestamptz not null default now()
);
create index if not exists motoboy_documentos_motoboy_idx on public.motoboy_documentos (motoboy_id);
create index if not exists motoboy_documentos_validade_idx on public.motoboy_documentos (validade);

create table if not exists public.turnos (
  id                  bigint generated always as identity primary key,
  loja_lead_id        bigint,                     -- lojas.lead_id (card do Kommo)
  loja_nome           text not null,
  cidade              text not null,
  data                date not null,
  inicio              time not null,
  fim                 time not null,
  valor               numeric,
  motoboy_id          bigint references public.motoboys(id),
  motoboy_original_id bigint references public.motoboys(id),  -- quem faltou, quando há cobertura
  status              text not null default 'aberto'
                      check (status in ('aberto','escalado','confirmado','falta','coberto','concluido','cancelado')),
  confirmado_em       timestamptz,
  obs                 text,
  criado_em           timestamptz not null default now(),
  atualizado_em       timestamptz not null default now()
);
create index if not exists turnos_data_idx on public.turnos (data, cidade);
create index if not exists turnos_motoboy_idx on public.turnos (motoboy_id, data);

create table if not exists public.coberturas (
  id            bigint generated always as identity primary key,
  turno_id      bigint not null references public.turnos(id) on delete cascade,
  motoboy_id    bigint not null references public.motoboys(id) on delete cascade,
  status        text not null default 'convidado'
                check (status in ('convidado','aceito','recusado','expirado')),
  enviado_em    timestamptz not null default now(),
  respondido_em timestamptz,
  unique (turno_id, motoboy_id)
);

create table if not exists public.ocorrencias (
  id          bigint generated always as identity primary key,
  motoboy_id  bigint references public.motoboys(id),
  turno_id    bigint references public.turnos(id),
  tipo        text not null check (tipo in ('acidente','atraso','problema_loja','pagamento','reclamacao','outro')),
  gravidade   text not null default 'media' check (gravidade in ('baixa','media','alta')),
  descricao   text not null,
  status      text not null default 'aberta' check (status in ('aberta','em_andamento','resolvida')),
  criado_em   timestamptz not null default now()
);

-- Histórico das conversas com o agente. Cada mensagem é uma linha e nunca é editada:
-- o modelo exige que o histórico seja reenviado exatamente como foi gerado.
create table if not exists public.mb_conversas (
  id            bigint generated always as identity primary key,
  telefone      text not null,
  motoboy_id    bigint references public.motoboys(id),
  iniciada_em   timestamptz not null default now(),
  ultima_msg_em timestamptz not null default now(),
  escalada      boolean not null default false
);
create index if not exists mb_conversas_tel_idx on public.mb_conversas (telefone, ultima_msg_em desc);

create table if not exists public.mb_mensagens (
  id          bigint generated always as identity primary key,
  conversa_id bigint not null references public.mb_conversas(id) on delete cascade,
  role        text not null check (role in ('user','assistant')),
  content     jsonb not null,
  criado_em   timestamptz not null default now()
);
create index if not exists mb_mensagens_conversa_idx on public.mb_mensagens (conversa_id, id);

-- O WhatsApp reenvia o webhook quando a resposta demora; guardamos o id para não responder duas vezes.
create table if not exists public.mb_eventos_whatsapp (
  mensagem_id text primary key,
  recebido_em timestamptz not null default now()
);

-- Aceite de cobertura num único UPDATE: o primeiro motoboy que aceitar leva o turno.
create or replace function public.assumir_turno(p_turno_id bigint, p_motoboy_id bigint)
returns boolean language plpgsql security definer set search_path = public as $$
declare ok boolean;
begin
  update turnos
     set motoboy_id = p_motoboy_id,
         status = case when status = 'falta' then 'coberto' else 'confirmado' end,
         confirmado_em = now(),
         atualizado_em = now()
   where id = p_turno_id and motoboy_id is null and status in ('aberto','falta');
  ok := found;
  if ok then
    update coberturas set status = 'aceito', respondido_em = now()
     where turno_id = p_turno_id and motoboy_id = p_motoboy_id;
    update coberturas set status = 'expirado'
     where turno_id = p_turno_id and motoboy_id <> p_motoboy_id and status = 'convidado';
  end if;
  return ok;
end $$;
revoke all on function public.assumir_turno(bigint, bigint) from public, anon, authenticated;

alter table public.motoboys            enable row level security;
alter table public.motoboy_documentos  enable row level security;
alter table public.turnos              enable row level security;
alter table public.coberturas          enable row level security;
alter table public.ocorrencias         enable row level security;
alter table public.mb_conversas        enable row level security;
alter table public.mb_mensagens        enable row level security;
alter table public.mb_eventos_whatsapp enable row level security;

insert into storage.buckets (id, name, public)
values ('motoboys', 'motoboys', false)
on conflict (id) do nothing;
