# Policy Wording: Permanent Exclusions

**Document ID**: UW-MAN-003
**Applies To**: All Health Retail Products

## 1. Standard Permanent Exclusions
The Insurer shall not be liable to make any payment under the policy in respect of any expenses incurred in connection with or in respect of:
1. **Cosmetic or Plastic Surgery**: Expenses for cosmetic or plastic surgery or any treatment to change appearance unless for reconstruction following an Accident, Burn(s), or Cancer.
2. **Self-Inflicted Injury**: Intentional self-injury, suicide, or attempted suicide.
3. **Substance Abuse**: Treatment for, alcoholism, drug or substance abuse, or any addictive condition and consequences thereof.
4. **Maternity**: Medical treatment expenses traceable to childbirth (including complicated deliveries and caesarean sections incurred during hospitalization) except ectopic pregnancy.
5. **Hazardous Sports**: Expenses related to any treatment necessitated due to participation as a professional in hazardous or adventure sports (e.g., para-jumping, rock climbing, mountaineering).
6. **Unproven Treatments**: Expenses related to any unproven treatment, services, and supplies for or in connection with any treatment. Unproven treatments are treatments, procedures or supplies that lack significant medical documentation to support their effectiveness.

## 2. Underwriting Override Logic
If the Risk Engine detects terms like "Cosmetic Surgery", "Rhinoplasty", or "Suicide Attempt" in the OCR extracted Hospitalization Summary, it must automatically repudiate the claim or decline the new underwriting proposal with the tag `PERMANENT_EXCLUSION_TRIGGERED`.
