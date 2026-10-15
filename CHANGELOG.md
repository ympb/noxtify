# Changelog

## 0.6.0 — Clique correto nos perfis e avatares de canais

- O botão principal da faixa agora usa os dados de `artist_profiles` / `artist`, nunca `creator`, para abrir a página do artista selecionado.
- Criado link independente **Publicado por** para abrir o canal que carregou a versão no YouTube.
- A busca enriquece os resultados em segundo plano com `uploader`, `channel_id` e `channel_url` por `yt-dlp`, sem atrasar a exibição inicial.
- Adicionado cache assíncrono de URLs de avatar, extraídas de metadados da página pública do canal. A capa da faixa não é confundida com a foto do uploader.
- A fila exibe miniatura da música, artista e canal publicador.
- O player e o nome na lista usam o artista da faixa; playlists, histórico e recomendações recebem os dois tipos de perfil separados.
- Renomeado o produto exibido para Noxtify e preparado um `PKGBUILD` estável para o pacote `noxtify`, mantendo `~/.local/share/nox-music` para preservar dados anteriores.

## 0.5.0 — Busca YouTube Music e descoberta adaptativa

- Removida a integração Spotify e restaurada a busca exclusiva do YouTube Music.
- Página inicial com estilos e recomendações adaptáveis ao histórico local.

## 0.3.0–0.4.0

- Melhorias de busca, miniaturas, perfis e recomendações.

## 0.1.0–0.2.0

- Primeira versão PyQt6/mpv, player, fila, letras e biblioteca.

## Ajustes de empacotamento local

- Preenchidos o mantenedor do AUR e os links do projeto com a conta `ympb`.
- Adicionada a etapa `check()` ao PKGBUILD para executar os 17 testes e verificar a sintaxe do aplicativo durante a compilação.
