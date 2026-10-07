-- Agente analista de marketing: um retrato por dia dos números do SendFlow e dos anúncios do painel.
create table if not exists public.mkt_snapshots (
  dia       date primary key,
  dados     jsonb not null,
  resumo    text,
  criado_em timestamptz not null default now()
);
alter table public.mkt_snapshots enable row level security;

-- Destino do resumo diário. Preencha grupo_id com o id do grupo de WhatsApp que deve receber.
insert into public.whatsapp_destinos (chave, nome, ativo)
values ('marketing', 'Resumo diário de marketing (definir grupo)', true)
on conflict (chave) do nothing;
