#!/bin/bash -e
# Creates the resources used by the migration functions, and deploys
# the Azure Function code to run in Azure.

source config.sh

if [[ -z $resourceGroup ]]; then
    resourceGroup="${1:-pmcmigrate}"
fi
if [[ -z $location ]]; then
    location=eastus
fi

keyvault="${resourceGroup}vault"
storage=$(echo "${resourceGroup}storage" | tr -d "-")
plan="${resourceGroup}plan"
functionapp="${resourceGroup}app"
sbns="${resourceGroup}bus"

function createResourceGroup() {
    echo "Creating $resourceGroup in "$location"..."
    az group create --name $resourceGroup --location "$location"
}

function createAppServicePlan() {
    # Create premium app service plan, which will hold the functions
    echo "Creating service plan '$plan'..."
    skuPlan="EP1"
    az functionapp plan create --name $plan --resource-group $resourceGroup --location "$location" --sku $skuPlan --max-burst 30 --min-instances 1 --is-linux true
}

function createStorageAccount() {
    echo "Creating storage account '$storage'..."
    az storage account create -n $storage -g $resourceGroup -l $location --sku Standard_LRS
}

function createServiceBus() {
    echo "Creating service bus '$sbns'..."
    az servicebus namespace create --resource-group $resourceGroup --name $sbns --location $location

    echo "Creating queue '$sbqueue' for '$sbns'..."
    az servicebus queue create --resource-group $resourceGroup --namespace-name $sbns --name pmcmigrate --max-delivery-count 3
}

function createFunctionApp() {
    echo "Creating function app '$functionapp'..."

    planId=$(az appservice plan show --name "$plan" --resource-group $resourceGroup --query 'id' -o tsv)

    az functionapp create -s "$storage" -g $resourceGroup -n $functionapp -p $planId --functions-version 4 --os-type linux --runtime python --runtime-version 3.9
}

function azFuncSet() {
    az functionapp config appsettings set --name $functionapp --resource-group $resourceGroup --settings "$1" &> /dev/null
}

function configureFunctionApp() {
    azFuncSet "WEBSITE_MAX_DYNAMIC_APPLICATION_SCALE_OUT=1"

    sbConnectionString=$(az servicebus namespace authorization-rule keys list --resource-group $resourceGroup --namespace-name $sbns --name RootManageSharedAccessKey --query primaryConnectionString --output tsv)
    azFuncSet "AzureServiceBusConnectionString=$sbConnectionString"


    azFuncSet "VNEXT_URL=$VNEXT_URL"
    azFuncSet "VCURRENT_SERVER=$VCURRENT_SERVER"
    azFuncSet "VCURRENT_PORT=$VCURRENT_PORT"
    azFuncSet "MSAL_CLIENT_ID=$MSAL_CLIENT_ID"
    azFuncSet "MSAL_SCOPE=$MSAL_SCOPE"
    azFuncSet "MSAL_CERT=$MSAL_CERT"
    azFuncSet "MSAL_AUTHORITY=$MSAL_AUTHORITY"
    azFuncSet "MSAL_SNIAUTH=$MSAL_SNIAUTH"
    azFuncSet "AAD_CLIENT_ID=$AAD_CLIENT_ID"
    azFuncSet "AAD_CLIENT_SECRET=$AAD_CLIENT_SECRET"
    azFuncSet "AAD_RESOURCE=$AAD_RESOURCE"
    azFuncSet "AAD_TENANT=$AAD_TENANT"
    azFuncSet "AAD_AUTHORITY_URL=$AAD_AUTHORITY_URL"
}

function publishFunctionApp() {
    echo "Publishing function app '$functionapp'..."
    for i in 1 2 3 4; do
        if [[ $i != 1 ]]; then
            echo "Retrying..."
        fi
        func azure functionapp publish $functionapp --python --build remote && break
        sleep 15
    done
    echo "Published '$functionapp'."
}

createResourceGroup
createAppServicePlan
createStorageAccount
createServiceBus
createFunctionApp
configureFunctionApp
publishFunctionApp
