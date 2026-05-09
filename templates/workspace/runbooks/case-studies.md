# Case Studies — {{WORKSPACE_NAME}}

> **Skeleton.** Cause-symptom-diagnosis-resolution catalog. Each entry
> is a repeat-pattern incident that's worth recognizing on first sight.
> `/debug` reads this file to match new incidents against known
> patterns *before* diving into logs.

> **When does an entry get added?**
> - You just resolved an incident that wasn't already here →
>   `/save` proposes adding (or you can `/idea capture` then promote)
> - For a postmortem-worthy outage (significant downtime, user impact),
>   write a full `runbooks/postmortems/<date>-<slug>.md` instead.
>   Case studies are short patterns; postmortems are full incidents.

## Format

```markdown
## <Pattern title>

- **Case**: <date> <env> ~<duration>
- **Symptom**: what the operator sees first
- **Root cause**: why it happens
- **Diagnostic queries**:
  ```bash
  # Concrete commands that confirm the diagnosis
  ```
- **Resolution**: minimal fix. If a prevention exists, list it.
- **Note**: anything that future-you would benefit from
```

---

<!-- Add real cases below as you encounter and resolve them. -->
