# P4P v0.1 — Operator Quick Check

Kort version.

Det her er ikke en QA-manual.

Det er den hurtige måde at afgøre om P4P faktisk taler sandt.

Det du vil bevise er:

- node er registreret i begge registries
- klienten kan finde noder videre via backup hvis primary dør
- node er kun grøn når den faktisk er registreret
- lukket node tager ikke imod ordre
- menu og ordre går direkte til node, ikke gennem registry

## 1. Hurtigste check først

Kør automattesten:

```bash
cd /path/to/p4p
demo-node/.venv/bin/python -m unittest discover -s tests -v
```

Hvis den er rød, så stop der.

Så er noget allerede ude af alignment.

## 2. Start labbet

```bash
cd /path/to/p4p/lab
./.venv/bin/uvicorn app:app --reload --port 8899
```

Åbn:

`http://127.0.0.1:8899`

Klik i den her rækkefølge:

1. `Start Primary Registry`
2. `Start Backup Registry`
3. `Start Client Server`
4. `Spawn Batch`

Brug `10` noder som default.

Klienten skal nu åbne på:

`http://127.0.0.1:8765/`

## 3. Hvad du skal se

For en node er der forskel på:

- `running`
- `ready`

`running` betyder bare processen lever.

`ready` betyder den faktisk er registreret og `/health` er grøn.

Det rigtige grønne billede er:

- primary kører
- backup kører
- noder kører
- noder bliver `ready`
- health-blokken viser to registries under `registered_registries`

Hvis en node kun er `running`, er det ikke godt nok.

Hvis du ser noget som i dit screenshot:

- `registered_registries` kun har primary
- backup står under `failed_registries`

så betyder det normalt bare én af to ting:

- backup var ikke startet endnu
- eller noden har ikke ramt næste heartbeat endnu

Vent cirka 60 sekunder eller restart noden.

## 4. Den rigtige test

Det vigtigste er ikke bare at noget starter.

Det vigtigste er failover-testen.

Gør sådan her:

1. start primary
2. start backup
3. start client server
4. spawn 10 nodes
5. åbn primary discover-linket
6. åbn backup discover-linket
7. bekræft at begge viser batchen
8. åbn klienten
9. klik `Discover Nodes`
10. stop primary registry i labbet
11. klik `Discover Nodes` igen

Det rigtige resultat er:

- klienten finder stadig noder
- den skifter over på backup
- menu virker stadig
- ordre virker stadig

Hvis discover dør når primary dør, så er failover-fortællingen falsk.

## 5. Closed-node test

Kør en node med `open=false`:

```bash
cd /path/to/p4p/demo-node
P4P_REGISTRY_URLS=http://127.0.0.1:8000,http://127.0.0.1:8002 \
P4P_NODE_BASE_URL=http://127.0.0.1:8201 \
P4P_NODE_OPEN=false \
./.venv/bin/uvicorn demo_node:app --port 8201
```

Det rigtige resultat er:

- node kan godt være `ready`
- men den må ikke dukke op i discover
- og ordre skal returnere:
  - `accepted: false`
  - `reason: "closed"`

Det er vigtigt.

`ready` betyder ikke `open`.

## 6. Fake-green test

Kør en node mod døde registries:

```bash
cd /path/to/p4p/demo-node
P4P_REGISTRY_URLS=http://127.0.0.1:8990,http://127.0.0.1:8991 \
P4P_NODE_BASE_URL=http://127.0.0.1:8301 \
./.venv/bin/uvicorn demo_node:app --port 8301
```

Check:

`http://127.0.0.1:8301/health`

Det rigtige resultat er:

- processen lever
- `/health` er `503`
- status er `not_ready`
- `registered_registries` er tom

Hvis den bliver grøn her, så lyver systemet.

## 7. Når du er færdig

Hvis du kun vil stole på én ting, så stol på den her kombi:

1. automattest er grøn
2. 10-node batch findes i både primary og backup
3. primary kan dø uden at discover dør
4. lukket node afviser ordre
5. falsk grøn er væk

Så er `v0.1` ikke perfekt.

Men så er den i det mindste ærlig.

## 8. Hvis noget fejler

Tre klassiske fejl:

### Node er `running` men ikke `ready`

Så er den ikke ordentligt registreret.

Kig i health-felterne og logs.

### Primary virker men backup gør ikke

Så er dual-registration ikke virkelig endnu.

Tjek at noden faktisk er startet med begge URLs i `P4P_REGISTRY_URLS`.

### Klienten finder intet efter primary dør

Så er failover ikke ægte endnu.

Det er ikke en lille fejl.

Det er hele pointen der fejler.

## 9. Hvis du vil have den fulde version

Læs:

`TEST-GUIDE.md`
