interface MSALConfig {
    auth: {
        clientId: string,
        authority: string,
        redirectUri: string,
        scope: string
    },
    cache: {
        cacheLocation: string,
        storeAuthStateInCookie: boolean,
    }
}

interface APIConfig {
    MSALConfig: MSALConfig
}
let config = {
    MSALConfig: {
        auth: {
            clientId: 'cb2d0012-33b1-48df-abc6-60957d6e8e19',
            authority: 'https://login.microsoftonline.com/72f988bf-86f1-41af-91ab-2d7cd011db47',
            redirectUri: "https://localhost:5173/",
            scope: "Forecast.Read"
        },
        cache: {
            cacheLocation: "sessionStorage",
            storeAuthStateInCookie: true,
        }
    }
};

export type { APIConfig, MSALConfig }