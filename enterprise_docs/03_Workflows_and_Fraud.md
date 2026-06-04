# Clarification Workflows & Fraud Detection Scenarios

## 1. Clarification & Additional Document Workflow

To prevent unnecessary hard rejections, the system employs an SLA-bound Clarification Workflow.

### A. Clarification Triggers
Before rejecting a case, the Risk Engine transitions the case to `Pending Additional Documents` under these triggers:
1. **HbA1c missing or > 7.5**: Trigger: `Request Latest HbA1c (within 3 months) & Physician Consultation Note`.
2. **ECG shows abnormality (e.g., T-wave inversion)**: Trigger: `Request 2D Echo & TMT Report`.
3. **Previous Claim Disclosed but No Discharge Summary**: Trigger: `Request Hospitalization Summary & Settlement Letter`.

### B. SLA & Broker Notifications
- **Status Change**: `Underwriter Review` → `Pending Additional Documents`
- **SLA Pause**: The 48-hour SLA clock pauses while waiting for the customer/broker.
- **Auto-Closure**: If documents are not uploaded within 15 days, the system auto-transitions the case to `Closed - Dropped`.
- **Notification Template**:
  > *"Dear Broker, Case #CASE-8F9B2A is pending. The underwriter has requested: [Latest Blood Sugar Reports]. Please upload these within 15 days to resume underwriting."*

---

## 2. Fraud Detection Rules (ArangoDB Graph Models)

The system queries ArangoDB for entity relationships to catch sophisticated fraud rings that traditional relational databases miss.

### A. Graph Extraction Entities & Relationships
- **Nodes**: `Applicant`, `Hospital`, `Doctor`, `Agent/Broker`, `Mobile Number`, `Bank Account`
- **Edges**: `TREATED_AT`, `TREATED_BY`, `SUBMITTED_BY`, `SHARES_MOBILE_WITH`

### B. Realistic Fraud Scenarios

#### Scenario 1: The "Shady Clinic" Ring
- **Detection Logic**: 
  If `Applicant A`, `Applicant B`, and `Applicant C` all have `TREATED_AT` relationships to `Clinic_XYZ` within the same month, AND `Clinic_XYZ` has a historical `FLAGGED_FOR_FRAUD` tag.
- **System Action**: Immediately set Risk Score to `100`, assign Status to `Referred` (Investigation Team), and halt STP.

#### Scenario 2: Forged/Copied Lab Reports
- **Detection Logic**:
  OCR extracts exact matching biomarker strings (e.g., RBC 4.52, WBC 8400, Platelets 2.1L) across two different `Applicant` nodes submitted on different dates.
- **Graph Path**: `Applicant_1` --(HAS_REPORT_DATA)--> `Lab_Hash_XYZ` <-- `Applicant_2`
- **System Action**: Flag for Document Forgery.

#### Scenario 3: Identity Masking (Shared Data)
- **Detection Logic**:
  Two `Applicant` nodes have different names and PAN cards, but they share the exact same `Mobile Number` or `Bank Account` node.
- **System Action**: Raise `Identity Mismatch Alert`. Route to Senior Underwriter.
