# Resume site

A private website built with [resume_builder](https://github.com/kumar0384/resume_builder). The content is stored encrypted (`resume.json.enc`), and the site is only reachable through a private link; the plain address shows an empty page.

## How it works

- The resume_builder app's **Publish** encrypts the resume with your **site key** and pushes `resume.json.enc` here.
- Each push runs [`.github/workflows/publish.yml`](.github/workflows/publish.yml). It decrypts the file with the `RESUME_SITE_KEY` repository secret and publishes the site under a secret folder derived from the key. It also writes nothing readable to the logs and deletes its downloadable build after deploying.
- Get the private link from the app: **Profiles → Live site → Copy link**.

## One-time setup

1. **Pages:** Settings → Pages → *Build and deployment* → Source: **GitHub Actions**.
2. **Site key:** in the app, click **Publish** (or **Site key…**) and choose to create a key. The app copies it and opens *Settings → Secrets and variables → Actions → New repository secret*. Name it `RESUME_SITE_KEY`, paste the key, and save.
3. Publish again from the app (or run the workflow from the Actions tab).

To publish from another computer: clone this repo there, then in the app use **Site key… → Yes** on the first computer to copy the key, and **Site key… → No → paste** on the second.

Optional: the workflow builds with the copy of resume_builder in `tool/` (version in `tool/VERSION`). To always use the latest version from the private resume_builder repo, add a read-only fine-grained token for it as the repository secret `RESUME_BUILDER_TOKEN`.

## Notes

- Keep the site key private: with it, anyone could decrypt `resume.json.enc` and work out the link.
- Creating a new key changes the private link; links you've already sent stop working.
- Anyone you send the link to can forward it. Pages are marked noindex, so search engines that respect it won't list them.
