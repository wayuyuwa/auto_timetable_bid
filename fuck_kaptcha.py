import ddddocr


ocr = ddddocr.DdddOcr()
def getKaptchaText(image: bytes):
    return ocr.classification(image)

if __name__ == "__main__":

    from selenium import webdriver
    from selenium.webdriver.common.by import By

    driver = webdriver.Chrome()

    driver.get("https://unitreg.utar.edu.my/portal/courseRegStu/login.jsp")

    while (input("Continue? :") == ""):
        kaptcha_img = driver.find_element(By.XPATH, "//input[@name='kaptchafield']/../img[1]").screenshot_as_png

        print(type(kaptcha_img))
        
        with open("kaptcha.png", "wb") as file:
            file.write(kaptcha_img)

        getKaptchaText(kaptcha_img)
        driver.refresh()

    driver.quit()
    print("Fuck!")