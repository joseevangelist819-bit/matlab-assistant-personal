# Private GitHub upload checklist

- [ ] Create the GitHub repository with visibility set to **Private**.
- [ ] Do not initialize the remote repository with a README, `.gitignore`, or license.
- [ ] Confirm `git status --short` lists only intended source, tests, examples, and documentation.
- [ ] Confirm no file is 100 MB or larger.
- [ ] Confirm secret and private-path scans return no matches.
- [ ] Push the local `main` branch.
- [ ] Verify the repository remains Private under GitHub repository settings.
- [ ] Add collaborators only when necessary.
