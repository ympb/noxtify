# Publicar Noxtify no AUR para permitir `yay -S noxtify`

O arquivo compactado não cria sozinho uma entrada no AUR. Para que outra pessoa instale com `yay -S noxtify`, o código precisa estar num repositório Git público e os metadados do pacote precisam ser enviados ao AUR pelo mantenedor.

> Antes de começar, abra https://aur.archlinux.org/packages/noxtify e confirme que o nome ainda está livre. A pesquisa web não é uma garantia de disponibilidade em tempo real. Se já houver um pacote chamado `noxtify`, será necessário escolher outro nome.

## 1. Prepare o CachyOS

```bash
sudo pacman -S --needed base-devel git openssh python-pytest
```

Extraia o ZIP do Noxtify e entre na pasta do projeto (aquela que contém `PKGBUILD`, `LICENSE`, `README.md` e `nox_music/`).

## 2. Crie o repositório público do código

No GitHub, crie um repositório público chamado **noxtify**. Não marque a opção para adicionar README, `.gitignore` ou licença se você vai enviar os arquivos já existentes no projeto.

O `PKGBUILD` e o User-Agent do aplicativo já estão configurados para o usuário GitHub `ympb`, e o mantenedor foi preenchido como `ympb <manoely.games@gmail.com>`. Esse e-mail ficará visível publicamente nos metadados do AUR.

Na pasta extraída do projeto, configure o Git e execute:

```bash
git config user.name "ympb"
git config user.email "manoely.games@gmail.com"
git init -b main
git add .
git commit -m "Initial Noxtify 0.6.0 release"
git remote add origin https://github.com/ympb/noxtify.git
git push -u origin main
git tag v0.6.0
git push origin v0.6.0
```

Antes dos comandos acima, crie no GitHub um repositório público vazio chamado `noxtify` dentro da conta `ympb`. Se você alterar o código depois de criar a tag, publique uma nova versão (por exemplo `v0.6.1`) e atualize `pkgver` no `PKGBUILD` antes de enviar a atualização ao AUR.

## 3. Teste o pacote localmente

Ainda na pasta do projeto, confirme os testes e a sintaxe:

```bash
python -m pytest -q
python -m py_compile nox_music/app.py
bash -n PKGBUILD
makepkg --syncdeps --cleanbuild
```

`makepkg` deve buscar a tag `v0.6.0` que você já enviou ao GitHub, montar um pacote `.pkg.tar.zst` e parar se o URL ou os metadados estiverem errados. Se ele falhar, corrija antes de publicar no AUR. Quando puder, valide também em instalação limpa.

## 4. Configure a conta AUR

1. Crie/entre na conta em https://aur.archlinux.org/.
2. Nas configurações da conta AUR, adicione sua chave pública SSH. Se você ainda não tem uma, crie uma chave:

   ```bash
   ssh-keygen -t ed25519 -C "manoely.games@gmail.com"
   cat ~/.ssh/id_ed25519.pub
   ```

3. Copie a saída completa de `cat ~/.ssh/id_ed25519.pub` para a configuração SSH da conta AUR. Nunca compartilhe o arquivo privado `~/.ssh/id_ed25519`.
4. Teste a autenticação:

   ```bash
   ssh -T aur@aur.archlinux.org
   ```

## 5. Envie o pacote `noxtify` ao AUR

Depois de verificar que `noxtify` está disponível, clone a árvore Git do AUR:

```bash
git clone ssh://aur@aur.archlinux.org/noxtify.git noxtify-aur
cd noxtify-aur
cp /CAMINHO/ATE/noxtify/PKGBUILD ./PKGBUILD
makepkg --printsrcinfo > .SRCINFO
makepkg --syncdeps --cleanbuild
```

Substitua `/CAMINHO/ATE/noxtify` pelo caminho real da pasta extraída. O primeiro clone é o repositório do AUR; se o servidor disser que o repositório não existe, confira a disponibilidade do nome e siga o fluxo atual de criação de pacote novo na interface/documentação do AUR.

Se a compilação local passou, envie os dois arquivos obrigatórios:

```bash
git add PKGBUILD .SRCINFO
git commit -m "Initial import: Noxtify 0.6.0"
git push
```

Todo push ao AUR deve incluir `.SRCINFO` atualizado. Sempre regenere-o depois de mudar a versão, dependências, URL ou outro metadado do `PKGBUILD`:

```bash
makepkg --printsrcinfo > .SRCINFO
```

## 6. Teste a instalação final

Depois que o pacote aparecer na página `https://aur.archlinux.org/packages/noxtify`:

```bash
yay -S noxtify
```

Para atualizar um pacote já publicado, atualize a versão no `PKGBUILD`, recrie e publique a tag correspondente no GitHub, execute `makepkg --printsrcinfo > .SRCINFO`, teste com `makepkg --syncdeps --cleanbuild` e envie o commit atualizado para o AUR.

## Referências oficiais

- [ArchWiki — AUR](https://wiki.archlinux.org/title/Arch_User_Repository)
- [ArchWiki — Diretrizes de envio ao AUR](https://wiki.archlinux.org/title/AUR_submission_guidelines)
- [ArchWiki — `.SRCINFO`](https://wiki.archlinux.org/title/.SRCINFO)
