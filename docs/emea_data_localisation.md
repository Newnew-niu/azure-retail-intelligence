# EMEA data localisation matrix

Does the law require personal data to stay in the country, and under what conditions may it leave?
Six jurisdictions, each statement tied to an official or regulator source and to how far that source
was actually read.

**Checked on 2026-11-26.** Laws change; the date of each source is given. This is an engineering
reference for this EU-hosted platform ([GOVERNANCE.md section 5](../GOVERNANCE.md#5-data-residency)),
not legal advice.

## How to read the status column

| Status | Meaning |
|---|---|
| ✅ Read | The official text or regulator page was read and the statement checked against it |
| 🟡 Official guidance | Checked against official guidance, not the statute itself |
| 🟠 Secondary | Checked against a legal database that reproduces the official text, not the official portal |
| ⚪ Not verified | The official source could not be read; the statement is a lead to check, not a finding |

## Matrix

| Jurisdiction | Law and current version | General data localisation? | Cross-border transfer conditions | Regulator | Status |
|---|---|---|---|---|---|
| **EU** | GDPR, Regulation (EU) 2016/679 | No general rule known; not verified against the text this session [E1] | Adequacy decision, otherwise appropriate safeguards (standard contractual clauses, binding corporate rules), otherwise narrow derogations (GDPR Chapter V) [E1]. 17 adequacy entries listed, incl. Switzerland, the UK (renewed December 2025) and US organisations in the EU-US Data Privacy Framework (decision of 10 July 2023) [E2]. SCCs: Implementing Decision (EU) 2021/914 of 4 June 2021, in effect from 27 September 2021 [E3] | National supervisory authorities; EDPB | Adequacy list ✅ · SCC decision 🟡 · Chapter V text ⚪ |
| **UK** | UK GDPR and DPA 2018, as amended by the Data (Use and Access) Act 2025 (c. 18). Transfer changes (Sch. 7) in force 5 February 2026 (S.I. 2026/82) [U1] [U2] | None found in the sources read; transfers are permitted when one of three routes applies [U3] [U4] | Art. 44A: transfer allowed if (a) approved by regulations (Art. 45A), (b) under appropriate safeguards (Art. 46: IDTA, the ICO Addendum, BCRs, codes, certification) or (c) a derogation (Art. 49). The test is that protection is "not materially lower" (Art. 45B), applied by the exporter "reasonably and proportionately" for safeguards. New Art. 49A lets the Secretary of State restrict categories of transfer [U1] [U3] [U4] | ICO | ✅ |
| **Switzerland** | Federal Act on Data Protection (FADP, SR 235.1) of 25 September 2020, in force 1 September 2023; Data Protection Ordinance (DPO, SR 235.11) [C1] | Not addressed by the source read ⚪ | Art. 16(1) FADP: Federal Council adequacy decision; Annex 1 DPO lists all EU and EEA states, and the US from 15 September 2024 for DPF-certified companies only. Otherwise Art. 16(2)(d): standard clauses approved, issued or recognised by the FDPIC (EU SCCs 2021/914 with Swiss adaptations; Council of Europe C108+ model clauses). Exceptions in Art. 17. Using recognised SCCs no longer has to be reported since 1 September 2023 [C1] | FDPIC | 🟡 (FDPIC guidance, last amended 12 February 2025) |
| **Türkiye** | Law No. 6698 (KVKK), Art. 9 replaced by Art. 34 of Law No. 7499 (Official Gazette 12 March 2024, No. 32487), in force 1 June 2024; old Art. 9(1) applied in parallel until 1 September 2024 [T1]. By-Law on transfers abroad, Official Gazette 10 July 2024, No. 32598 [T2] | Art. 9 contains none; Art. 9(10) reserves transfer rules in other laws, so sector rules may add requirements. Rest of Law 6698 not read ⚪ | Art. 9: adequacy decision by the Board, published in the Official Gazette, reviewed at least every four years. Otherwise appropriate safeguards: agreement between public bodies (Board permission), Board-approved binding corporate rules, Board-announced standard contract, or written undertaking (Board permission). A signed standard contract must be notified to the Authority within five business days and used without changes. Otherwise only occasional ("arızi") transfers on listed grounds, e.g. explicit consent after risk disclosure, contract performance, legal claims [T1] [T2] | KVKK (Personal Data Protection Authority) | ✅ (Official Gazette) |
| **Saudi Arabia** | Personal Data Protection Law, Royal Decree M/19 of 9/2/1443H (16 September 2021), amended by Royal Decree M/148 of 5/9/1444H [S1] | Not determinable from the sources read ⚪ | Art. 29 PDPL and the Implementing Regulations. For a jurisdiction without adequacy the controller checks that the transfer does not affect national security or the Kingdom's vital interests, transfers only the minimum data, respects data subject rights, has an established purpose, uses an appropriate safeguard (Binding Common Rules, standard contractual clauses) and has done a risk assessment. The adequacy list "shall be adopted" (as of December 2023) [S2] | SDAIA | Transfer conditions 🟡 · decree data ⚪ (seen only in the official portal's search listing) |
| **Russia** | Federal Law No. 152-FZ "On Personal Data"; Art. 18(5) as amended by Federal Law No. 23-FZ of 28 February 2025, in force 1 July 2025 [R1] [R2] | **Yes.** When collecting personal data of Russian citizens, recording, systematisation, accumulation, storage, clarification and retrieval *using databases located outside Russia* are not permitted (exceptions: Art. 6(1) items 2, 3, 4, 8). The Ministry of Digital Development reads this as covering copies too [R1] [R2] | After localisation, a cross-border transfer needs a prior notice to Roskomnadzor (Art. 12(3)). Roskomnadzor decides within 10 working days (Art. 12(9)). To countries on the adequacy list the operator may transfer after notifying; to others, not until that period ends (Art. 12(10), (11)). Roskomnadzor may ban or restrict a transfer (Art. 12(7), (8), (12)). Law No. 265-FZ of 26 July 2026 amends Art. 12(2), (5), (10), (11) and was marked not yet in force [R3] | Roskomnadzor | 🟠 (consultant.ru; the official portals were unreachable) |

## What it means for an EU-hosted platform

- EU, UK and Swiss data can be stored in an EU Azure region; flows between them rest on adequacy
  decisions (the EU's for the UK and Switzerland [E2]; Switzerland lists all EU/EEA states [C1]).
- Türkiye and Saudi Arabia do not require local storage in the provisions read, but moving data out
  needs a documented route: for Türkiye usually the Board's standard contract plus the five-day
  notification [T1]; for Saudi Arabia a safeguard and a risk assessment [S2].
- Russian citizens' data cannot be collected into an EU-only platform: the primary database must be
  in Russia [R1], which no EU region can satisfy.

## Sources

| ID | Source | Publisher | What was read |
|---|---|---|---|
| E1 | [GDPR on EUR-Lex](https://eur-lex.europa.eu/eli/reg/2016/679/oj) | Publications Office of the EU | ⚪ EUR-Lex returned an empty response to automated requests; to check in a browser |
| E2 | [Adequacy decisions](https://commission.europa.eu/law/law-topic/data-protection/international-dimension-data-protection/adequacy-decisions_en) | European Commission | ✅ Full page: list of decisions, UK renewal (press release 19 December 2025), DPF decision dated 10 July 2023 |
| E3 | [FDPIC guidance on standard clauses](https://www.edoeb.admin.ch/dam/en/sd-web/smvG75WY5Vsi/%C3%9Cbermittlung%20von%20Personendaten%20-%20SCC_EN.pdf), citing [Decision (EU) 2021/914](http://data.europa.eu/eli/dec_impl/2021/914/oj) | FDPIC (Switzerland) | 🟡 Date and effect of the EU decision as cited by the FDPIC; the decision itself not read |
| U1 | [Data (Use and Access) Act 2025, Schedule 7](https://www.legislation.gov.uk/ukpga/2025/18/schedule/7) | legislation.gov.uk | ✅ Revised text with commencement notes |
| U2 | [ICO statement on commencement, 5 February 2026](https://ico.org.uk/about-the-ico/media-centre/news-and-blogs/2026/02/statement-on-the-commencement-of-the-data-use-and-access-act-duaa/) | ICO | ✅ |
| U3 | [ICO: complying with the transfer rules](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/international-transfers/a-guide-to-international-transfers/how-do-we-comply-with-the-transfer-rules-if-were-initiating-the-restricted-transfer/) | ICO | ✅ |
| U4 | [ICO: DUAA schedules summary](https://ico.org.uk/about-the-ico/what-we-do/legislation-we-cover/data-use-and-access-act-2025/the-data-use-and-access-act-2025-duaa-summary-of-the-changes/schedules/) | ICO | ✅ (summary dated 19 June 2025) |
| C1 | [FDPIC: transfer to a country without adequate protection based on standard clauses](https://www.edoeb.admin.ch/dam/en/sd-web/smvG75WY5Vsi/%C3%9Cbermittlung%20von%20Personendaten%20-%20SCC_EN.pdf) | FDPIC | ✅ Full document (published 27 August 2021, last amended 12 February 2025). The FADP and DPO on [Fedlex](https://www.fedlex.admin.ch/eli/cc/2022/491/en) need JavaScript and were not read |
| T1 | [Law No. 7499, Official Gazette 12 March 2024](https://www.resmigazete.gov.tr/eskiler/2024/03/20240312-1.htm) | Resmî Gazete | ✅ Art. 34 (new Art. 9 of Law 6698), Art. 36 (transitional), Art. 40 (entry into force) |
| T2 | [By-Law on transfers abroad, Official Gazette 10 July 2024](https://www.resmigazete.gov.tr/eskiler/2024/07/20240710-2.htm) | Resmî Gazete | ✅ Arts. 6, 9, 10, 14, 16, 18. The consolidated [Law 6698 PDF](https://www.mevzuat.gov.tr/mevzuatmetin/1.5.6698.pdf) and [kvkk.gov.tr](https://www.kvkk.gov.tr/Icerik/6649/Personal-Data-Protection-Law) could not be read |
| S1 | [PDPL on the Bureau of Experts portal](https://laws.boe.gov.sa/boelaws/laws/lawdetails/b7cfae89-828e-4994-b167-adaa00e37188/1) | Bureau of Experts at the Council of Ministers | ⚪ Connection refused; decree numbers and dates seen only in the portal's search listing |
| S2 | [Guide to the Saudi PDPL, v1.0, December 2023](https://dgp.sdaia.gov.sa/wps/wcm/connect/85a664fd-6e4e-4edb-bab4-1cbdb02ba6d5/Guide+to+the+saudi+PDP+law+HANDBOOK__%D9%90EN.pdf?MOD=AJPERES) | SDAIA | 🟡 Full guide, Section 09. The [law](https://sdaia.gov.sa/en/SDAIA/about/Documents/PersonalDataProtectionLaw.pdf) and [Implementing Regulation](https://sdaia.gov.sa/en/SDAIA/about/Documents/ImplementingRegulation.pdf) PDFs were rejected by the site |
| R1 | [152-FZ Art. 18, consolidated, as of 26.07.2026](https://www.consultant.ru/document/cons_doc_LAW_61801/cbf4e15b7c330f9372e876cdf2bc928bad7950ef/) | ConsultantPlus (legal database) | 🟠 |
| R2 | [Ministry of Digital Development letter of 12.05.2025 No. П25-44929](https://www.consultant.ru/document/cons_doc_LAW_511584/) | ConsultantPlus | 🟠 The letter states it is not a normative legal act |
| R3 | [152-FZ Art. 12, consolidated, as of 26.07.2026](https://www.consultant.ru/document/cons_doc_LAW_61801/e4ebbe1780de623c7cf32a59ca82a7bb523a25dd/) | ConsultantPlus | 🟠 Roskomnadzor's [English text](https://pd.rkn.gov.ru/authority/p146/p164/) and [notice form](https://pd.rkn.gov.ru/cross-border-transmission/form/) refused the connection |

## Open checks

Before any row is relied on, these need a person with a browser:

1. GDPR Chapter V and Art. 1(3) on EUR-Lex (E1), and Decision 2021/914 itself (E3).
2. FADP Arts. 16, 17 and DPO Annex 1 on Fedlex, including whether the UK is listed (C1).
3. The rest of Law 6698 on mevzuat.gov.tr, for any localisation rule outside Art. 9 (T1).
4. PDPL Art. 29, the transfer regulation and its current version, and the enforcement date (S1, S2).
5. Russian Art. 18(5) and Art. 12 on pravo.gov.ru, and whether Law 265-FZ of 26 July 2026 has
   entered into force (R1, R3).
6. Sector rules that add localisation (e.g. banking, telecoms, health, public sector) were out of scope.
