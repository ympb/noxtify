# Noxtify

Player musical desktop para Linux com interface preta AMOLED, busca no YouTube Music, capas, perfis separados para artista e canal publicador, fila, letras sincronizadas, biblioteca local e recomendações adaptativas.

**Versão:** 0.6.0

## O que mudou na 0.6.0

- O clique no nome do artista abre o perfil do intérprete da faixa clicada, independentemente da música que está tocando.
- O link **Publicado por** fica separado e abre o canal que enviou aquela versão.
- Os resultados do YouTube Music são enriquecidos em segundo plano com dados do canal por `yt-dlp`.
- Os avatares dos canais são extraídos da página pública do YouTube e guardados em cache local; a capa da faixa não é usada como avatar do publicador.
- A fila de reprodução mostra capa, artista e canal publicador.
- A busca, as capas, as playlists, o player, as letras e a descoberta adaptativa continuam disponíveis.

## Dependências

- Python
- PyQt6
- Requests
- ytmusicapi
- yt-dlp
- mpv

No CachyOS / Arch Linux:

```bash
sudo pacman -S --needed python python-pyqt6 python-requests python-ytmusicapi yt-dlp mpv
```

Para executar a partir do código-fonte:

```bash
python nox_music/app.py
```

Depois de instalado como pacote, use:

```bash
noxtify
```

## Testes puros

```bash
sudo pacman -S --needed python-pytest
python -m pytest -q
```

Os testes de lógica não exigem PyQt6 nem rede. A janela, a busca real do YouTube, a reprodução de áudio e o carregamento dos avatares devem ser conferidos num desktop Linux com rede.

## Artista versus publicador

- **Artista:** pessoa/banda associada à faixa nos metadados do YouTube Music. O clique abre a discografia/perfil do artista.
- **Publicado por:** canal que publicou o vídeo/versão que pode ser tocada. O clique abre o canal e tenta listar os vídeos públicos desse canal.

A fonte nem sempre inclui metadados estruturados de artista ou canal. Os resultados são enriquecidos em segundo plano; se o YouTube limitar a página, o avatar pode ficar no ícone de fallback.

Os dados locais antigos são preservados em `~/.local/share/nox-music`, de modo que a mudança do nome do aplicativo não apaga a biblioteca da versão anterior.

## Publicar no AUR

Consulte [`PACKAGING-AUR.md`](PACKAGING-AUR.md). O `PKGBUILD` já está preenchido com o mantenedor `ympb <manoely.games@gmail.com>` e aponta para `https://github.com/ympb/noxtify`. Esse repositório ainda precisa existir publicamente e conter a tag `v0.6.0` antes da compilação pelo AUR funcionar. O pacote só funcionará com `yay -S noxtify` depois que você publicar o código no GitHub, criar a tag de release, validar a compilação e enviar `PKGBUILD` e `.SRCINFO` para o AUR.

## Limitações conhecidas

- O YouTube pode mudar endpoints ou limitar o acesso, afetando busca, reprodução e avatares.
- Nem toda faixa identifica claramente o artista, especialmente uploads de fãs com títulos ambíguos.
- O fluxo de áudio é obtido com yt-dlp; mantenha esse pacote atualizado.
- Este artefato passou pelos testes da lógica e pela verificação de sintaxe, mas precisa de teste visual/de reprodução no CachyOS antes da publicação.

## Licença

MIT. Consulte [`LICENSE`](LICENSE).
