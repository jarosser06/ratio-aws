# Image is passed as a build arg by the framework
ARG IMAGE
FROM $IMAGE


RUN poetry config virtualenvs.create false

ADD . ${LAMBDA_TASK_ROOT}/ratio_aws
RUN rm -rf /var/task/ratio_aws/.venv

RUN cd ${LAMBDA_TASK_ROOT}/ratio_aws && poetry install --without dev
