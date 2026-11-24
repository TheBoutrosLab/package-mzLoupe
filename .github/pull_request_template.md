# Description
<!--- Briefly describe the changes included in this pull request  --->

### Closes #...  <!-- edit if this PR closes an Issue -->

<!--
Admin/maintainer: please edit the 'Pipeline Run Results' or 'Analysis Results' sections as needed for your project repo.
Then commit/push the changes so everyone uses this template for future PRs.

For example, if your project is a `pipeline`, then create a 'Pipeline Run Results' section.

If your project is a general data analysis project, then you may want to require an 'Analysis Results' section in order to test
code from each PR to help prevent creating new bugs.
-->

# Checklist
<!--- Please read each of the following items and confirm by replacing the [ ] with a [X] --->

- [ ] This PR **does *NOT* contain** Protected Health Information [(PHI)](https://www.hhs.gov/hipaa/for-professionals/privacy/laws-regulations/index.html). A repo may ***need to be deleted*** if such data is uploaded. <br> Disclosing PHI is a ***major problem***[^1] - Even ***a small leak can be costly***[^2].

- [ ] This PR **does *NOT* contain** germline genetic data[^3], RNA-Seq, DNA methylation, microbiome or other molecular data[^4].

[^1]: [UCLA Health reaches $7.5m settlement over 2015 breach of 4.5m patient records](https://healthitsecurity.com/news/ucla-health-reaches-7.5m-settlement-over-2015-breach-of-4.5m)
[^2]: [The average healthcare data breach costs $2.2 million, despite the majority of breaches releasing fewer than 500 records.](https://www.ponemon.org/local/upload/file/Sixth%20Annual%20Patient%20Privacy%20%26%20Data%20Security%20Report%20FINAL%206.pdf)
[^3]: [Genetic information is considered PHI.](https://www.genome.gov/about-genomics/policy-issues/Privacy#:~:text=In%202013%2C%20as%20required%20by,genetic%20information%20for%20underwriting%20purposes.)
  [Forensic assays can identify patients with as few as 21 SNPs](https://www.sciencedirect.com/science/article/pii/S1525157817305962)
[^4]: [RNA-Seq](https://www.nature.com/articles/ng.2248), [DNA methylation](https://ieeexplore.ieee.org/document/7958619), [microbiome](https://www.pnas.org/doi/pdf/10.1073/pnas.1423854112), or other molecular data can be used to predict genotypes (PHI) and reveal a patient's identity.


- [ ] This PR **does *NOT* contain** other non-plain text files, such as: compressed files, images (*e.g.* `.png`, .`jpeg`), `.pdf`, `.RData`, `.xlsx`, `.doc`, `.ppt`, or other output files.

_&emsp; To automatically exclude such files using a [.gitignore](https://docs.github.com/en/get-started/getting-started-with-git/ignoring-files) file, see [here](https://github.com/TheBoutrosLab/template-base/blob/main/.gitignore) for example._

- [ ] I have read the [code review guidelines](https://solid-adventure-l491og6.pages.github.io/latest/code-review-guidelines) and the [code review best practice on GitHub check-list](https://solid-adventure-l491og6.pages.github.io/latest/code-review-best-practices).

- [ ] The name of the branch is meaningful and well formatted following the [standards](https://solid-adventure-l491og6.pages.github.io/latest/code-review-best-practices), using \[AD_username (or 5 letters of AD if AD is too long)]-\[brief_description_of_branch].


### Documentation

- [ ] I have updated the documentation and dependency requirements where needed.
- [ ] I have documented relevant user-facing work in `CHANGELOG.md`.

<!--
Package version bumps are handled by the Prepare new release workflow.
pyproject.toml is the source of truth; frontend versions are synchronized
in the same release PR and checked in CI.
Finalize release runs when its automated release PR is merged.
Regular PRs should not manually bump package versions, set release dates,
create release tags, or draft GitHub releases.
-->

### Testing

<!-- List the checks run and their results; explain any checks that do not apply. -->

- [ ] I have added or updated tests where needed.
- [ ] Relevant Python and frontend checks passed locally and/or in CI.

Checks run and results:

<!-- Commands, outcomes, or a short explanation for documentation-only changes. -->
