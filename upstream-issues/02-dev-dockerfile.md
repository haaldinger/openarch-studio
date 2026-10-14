# Official Dockerfile can't build from a plain `mvn package` (gated base image + release-only artifacts)

## Summary
`server/openarch-app/src/main/docker/Dockerfile` documents this flow in its own
header:

```
# Before building the container image run:
#   ./mvnw package
# Then build the image with:
#   docker build -f src/main/docker/Dockerfile -t hyland/openarch-app-jvm .
```

But following it fails for an external developer, for two reasons.

## Problems
1. **Gated base image.** The build/runtime stages use
   `dhi.io/amazoncorretto:25-alpine3.23-dev@sha256:...` and
   `dhi.io/amazoncorretto:25-alpine3.23@sha256:...`. `dhi.io` (Docker Hardened
   Images) is not anonymously pullable, so `docker build` can't fetch the base.
2. **Release-only artifacts.** The Dockerfile copies:
   ```
   COPY target/licenses /deployments/licenses
   COPY target/*-3rd-Party-libraries.csv /deployments/licenses/
   ```
   A plain `mvn package` does not produce `target/licenses` or the
   `*-3rd-Party-libraries.csv` (they come from the license/release profile), so
   the `COPY` fails.
3. Minor: the header says `./mvnw package`, but there is no Maven wrapper
   (`mvnw`) in the repo.

## Expected behaviour
An external developer can build a runnable image from source following the
documented steps.

## Proposed fix
Add a developer-facing Dockerfile on a public base that needs only the fat jar,
e.g.:

```dockerfile
FROM eclipse-temurin:25-jre
WORKDIR /app
COPY target/openarch-app-*.jar /app/app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
```

…or make the license `COPY` lines conditional and document the `dhi.io`
auth requirement. Also add a Maven wrapper or correct the header to `mvn`.

## Context
Hit while standing up OpenArch locally to run a POC against it; built the jar
with `mvn -DskipTests package` and used exactly the minimal Dockerfile above to
get a working server image.
